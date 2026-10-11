'use strict';

/*
 * What a device, or a whole subnet, may reach: network by network, how much of it.
 *
 * The fog on the map is drawn from this. A network is one of five things to whoever looks:
 *   home   — where the onlooker lives;
 *   open   — the whole of it, every port;
 *   ports  — the whole of it, but only on some ports: drawn in stripes, the ports written on;
 *   hosts  — only some of the machines in it, by rules of their own: the network stays dark
 *            and those machines alone show through;
 *   some   — for a subnet: nothing for all of its devices, something for a few of them;
 *   shut   — nothing at all.
 *
 * No drawing here and nothing from the page — only the world as /api/map gives it. That way
 * the rules can be checked by the tests without a browser. The words for "any port" and "any
 * protocol" come in from outside: the server says them in the page's language, and they are
 * compared as said.
 */

class Sight {
  constructor(world, words) {
    this.world = world;
    this.anyPort = words.anyPort;
    this.anyProtocol = words.anyProtocol;
  }

  static number(ip) {
    const parts = String(ip).split('.').map(Number);
    if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return null;
    return ((parts[0] * 256 + parts[1]) * 256 + parts[2]) * 256 + parts[3];
  }

  /** A network's first and last address as numbers; null for a network that does not read. */
  static range(network) {
    const [base, bits] = String(network || '').split('/');
    const start = Sight.number(base);
    const size = Number(bits);
    if (start === null || !Number.isInteger(size) || size < 0 || size > 32) return null;
    const span = 2 ** (32 - size);
    const low = Math.floor(start / span) * span;
    return [low, low + span - 1];
  }

  /**
   * Whether the ranges together cover every address from low to high. Together, not one by
   * one: the router hands out one rule in pieces — "the whole of Lab" arrives as .0–.19, .20
   * and .21–.255 when .20 has rules of its own — and the pieces still make the whole.
   */
  static covers(ranges, low, high) {
    let reached = low;
    for (const [from, to] of [...(ranges || [])].sort((one, other) => one[0] - other[0])) {
      if (from > reached) break;
      if (to >= reached) reached = to + 1;
      if (reached > high) return true;
    }
    return false;
  }

  /**
   * Port labels in the order of their numbers, protocol by protocol: icmp, tcp 53, udp 53,
   * udp 123 — not "udp 123, udp 4752, udp 53", which is how text sorts.
   */
  static byPort(labels) {
    const key = (label) => {
      const [, protocol, ports] = String(label).match(/^(.*?)\s*(\d[\d,\s-]*)?$/);
      return { label, protocol, first: ports ? parseInt(ports, 10) : -1 };
    };
    return labels.map(key).sort((one, other) => one.protocol.localeCompare(other.protocol) || one.first - other.first)
      .map((one) => one.label);
  }

  /** The openings a device's own address passes, road by road: one place says which apply. */
  deviceRoads(device) {
    const homes = new Set(device.homes);
    const found = [];
    for (const road of this.world.roads) {
      if (!homes.has(road.source) || road.width === 'shut') continue;
      const seat = device.seats.find((one) => one.segment === road.source);
      const ip = seat ? Sight.number(seat.ip) : null;
      if (ip === null) continue;
      const mine = road.openings.filter((opening) => Sight.covers(opening.from, ip, ip));
      if (mine.length) found.push({ road, openings: mine });
    }
    return found;
  }

  /** What a device may reach, network by network. */
  ofDevice(device) {
    const homes = new Set(device.homes);
    const byTarget = new Map();
    for (const { road, openings } of this.deviceRoads(device)) {
      byTarget.set(road.target, [...(byTarget.get(road.target) || []), ...openings]);
    }
    return this.judgeAll((key) => homes.has(key), (key) => ({ all: byTarget.get(key) || [], few: [] }));
  }

  /**
   * What a subnet may reach, for all of its devices. An opening meant for a few of them is no
   * reach of the subnet's: it is told apart, so that one machine's rule does not light up a
   * whole network for everybody.
   */
  ofSegment(key) {
    const segment = this.world.segments.find((one) => one.key === key);
    const range = segment ? Sight.range(segment.network) : null;
    const byTarget = new Map();
    for (const road of this.world.roads) {
      if (road.source !== key || road.width === 'shut') continue;
      const found = byTarget.get(road.target) || { all: [], few: [] };
      for (const opening of road.openings) {
        const everyone = range ? Sight.covers(opening.from, range[0], range[1]) : true;
        (everyone ? found.all : found.few).push(opening);
      }
      byTarget.set(road.target, found);
    }
    return this.judgeAll((target) => target === key, (target) => byTarget.get(target) || { all: [], few: [] });
  }

  /** Every network on the map and the internet, judged one by one. */
  judgeAll(isHome, openingsOf) {
    const verdicts = new Map();
    const keys = [...this.world.segments.map((one) => one.key), this.world.ends.internet];
    for (const key of keys) {
      verdicts.set(key, isHome(key) ? { state: 'home' } : this.judge(key, openingsOf(key)));
    }
    return verdicts;
  }

  label(opening) {
    return opening.ports === this.anyPort ? opening.protocol : `${opening.protocol} ${opening.ports}`;
  }

  every(opening) {
    return opening.ports === this.anyPort && opening.protocol === this.anyProtocol;
  }

  /**
   * How much of one network the openings reach: what all of the onlookers share, and, beside it,
   * what a few devices of a subnet have on their own — `others`, each told as that device's own
   * reach is. A network open to everyone needs no others; one shut to everyone but open to a
   * few is "some".
   */
  judge(key, { all, few }) {
    const own = this.reach(key, all);
    if (!few.length || own.state === 'open') return own;
    const others = this.others(key, few);
    if (own.state === 'shut') return { state: 'some', members: others.map((one) => one.name), others };
    return { ...own, others };
  }

  /** How much of one network some openings reach: all of their pieces taken together. */
  reach(key, openings) {
    const segment = this.world.segments.find((one) => one.key === key);
    const range = segment ? Sight.range(segment.network) : null;
    const reaches = (list) => list.length > 0
      && (!range || Sight.covers(list.flatMap((opening) => opening.to || []), range[0], range[1]));
    if (reaches(openings.filter((opening) => this.every(opening)))) return { state: 'open' };
    if (reaches(openings)) return { state: 'ports', ports: Sight.byPort([...new Set(openings.map((opening) => this.label(opening)))]) };
    if (openings.length) return { state: 'hosts', hosts: this.hosts(key, openings) };
    return { state: 'shut' };
  }

  /**
   * The machines of a network the openings lead to, each with its ports. An address no device
   * holds is still told, by itself: a rule for a machine that is away is still a rule.
   */
  hosts(key, openings) {
    const found = new Map();
    const add = (id, entry, opening) => {
      const kept = found.get(id) || { ...entry, ports: [] };
      const label = this.every(opening) ? '' : this.label(opening);
      if (label && !kept.ports.includes(label)) kept.ports.push(label);
      if (!label) kept.any = true;
      found.set(id, kept);
    };
    for (const opening of openings) {
      let named = false;
      for (const device of this.world.devices) {
        const seat = device.seats.find((one) => one.segment === key);
        const ip = seat ? Sight.number(seat.ip) : null;
        if (ip !== null && Sight.covers(opening.to, ip, ip)) {
          add(device.key, { device: device.key, name: device.name, ip: seat.ip }, opening);
          named = true;
        }
      }
      if (!named) add(opening.target, { device: '', name: '', ip: opening.target }, opening);
    }
    return [...found.values()].map(({ any, ...host }) => ({ ...host, ports: any ? [] : Sight.byPort(host.ports) }));
  }

  /**
   * The few devices of the subnet some openings are meant for, each with what its own openings
   * reach of the network. An address no device holds is still told, by itself: a rule for a
   * device that is away is still a rule.
   */
  others(key, openings) {
    const holds = (device, opening) => device.seats.some((seat) => {
      const ip = Sight.number(seat.ip);
      return ip !== null && Sight.covers(opening.from, ip, ip);
    });
    const found = [];
    for (const device of this.world.devices) {
      const mine = openings.filter((opening) => holds(device, opening));
      if (mine.length) found.push({ device: device.key, name: device.name || device.seats[0].ip, verdict: this.reach(key, mine) });
    }
    const loose = openings.filter((opening) => !this.world.devices.some((device) => holds(device, opening)));
    for (const source of [...new Set(loose.map((opening) => opening.source))]) {
      found.push({ device: '', name: source, verdict: this.reach(key, loose.filter((opening) => opening.source === source)) });
    }
    return found;
  }
}

if (typeof module === 'object' && module.exports) module.exports = { Sight };

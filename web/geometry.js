'use strict';

/*
 * Where the roads run: right angles only, one road per castle, bridges where roads cross.
 *
 * Every pair of castles talks through the customs town, so a castle needs exactly one road —
 * what may pass along it is written on the signs, not drawn as a separate road per pair.
 *
 * No drawing here and nothing from the page — just points. That way the promise «roads do not
 * cross» is a thing the tests can check without a browser.
 */

class Corridor {
  /** The one road between a castle and the customs town: right angles only. */
  constructor(castle, town) {
    this.castle = castle;
    this.town = town;
    //: Every road of this castle: they share one road to the customs house, and differ by sign.
    this.ways = [];
    const away = { x: castle.place.x - town.x, y: castle.place.y - town.y };
    this.flat = Math.abs(away.x) >= Math.abs(away.y);
    this.side = (this.flat ? Math.sign(away.x) : Math.sign(away.y)) || 1;
    //: The gate in the customs wall: the page places it once it has counted that wall's neighbours.
    this.townSize = Corridor.TOWN;
    this.along = 0;
  }

  static WIDE = 24;
  static GAP = 26;
  //: The smallest customs house. When a wall gets crowded, the page makes it larger.
  static TOWN = { width: 120, height: 96 };

  add(road, way) {
    this.ways.push({ road, way });
  }

  get width() {
    return Corridor.WIDE;
  }

  /**
   * Gates in the customs walls: every corridor has its own.
   *
   * Otherwise two corridors would enter at one point and merge. When one wall gets crowded
   * the customs house grows: a busy crossroads ought to look big.
   */
  static gates(corridors) {
    const walls = { flat: [[], []], upright: [[], []] };
    for (const corridor of corridors) {
      walls[corridor.flat ? 'flat' : 'upright'][corridor.side > 0 ? 0 : 1].push(corridor);
    }
    const need = (side) => side.reduce((sum, corridor) => sum + corridor.width + Corridor.GAP, 0);
    const size = {
      width: Math.min(340, Math.max(Corridor.TOWN.width, ...walls.upright.map(need))),
      height: Math.min(340, Math.max(Corridor.TOWN.height, ...walls.flat.map(need))),
    };
    for (const [kind, sides] of Object.entries(walls)) {
      for (const side of sides) {
        const room = kind === 'flat' ? size.height : size.width;
        side.sort((one, other) => (kind === 'flat'
          ? one.castle.place.y - other.castle.place.y : one.castle.place.x - other.castle.place.x));
        let edge = -room / 2;
        for (const corridor of side) {
          const step = (room - Corridor.GAP) / side.length;
          corridor.along = edge + step / 2 + Corridor.GAP / 2;
          corridor.townSize = size;
          edge += step;
        }
      }
    }
    return size;
  }

  /** The middle of the corridor: what bridges are measured against. */
  get spine() {
    return this.path(0);
  }

  path(shift) {
    const box = this.castle.box;
    const half = { x: this.townSize.width / 2, y: this.townSize.height / 2 };
    if (this.flat) {
      const gate = { x: this.side > 0 ? box.x : box.x + box.width, y: this.castle.place.y + shift };
      const townGate = { x: this.town.x + half.x * this.side, y: this.town.y + this.along + shift };
      const turn = (gate.x + townGate.x) / 2 + shift;
      return [gate, { x: turn, y: gate.y }, { x: turn, y: townGate.y }, townGate];
    }
    const gate = { x: this.castle.place.x + shift, y: this.side > 0 ? box.y : box.y + box.height };
    const townGate = { x: this.town.x + this.along + shift, y: this.town.y + half.y * this.side };
    const turn = (gate.y + townGate.y) / 2 + shift;
    return [gate, { x: gate.x, y: turn }, { x: townGate.x, y: turn }, townGate];
  }

  static line(points) {
    return points.map((point, order) => `${order ? 'L' : 'M'} ${point.x} ${point.y}`).join(' ');
  }

}

class Bridges {
  /**
   * Where lanes of different corridors cross, road does not merge into road: one goes over.
   *
   * It is worked out from the lanes themselves, not the centre line: a corridor is wider than
   * its middle, and it is usually the edges that cross. Crossings close together gather into
   * one bridge — otherwise six little bridges would sprout at a single junction.
   */
  static find(corridors) {
    const ways = corridors.map((corridor, order) => ({ order, points: corridor.spine }));
    const hits = [];
    for (const upper of ways) {
      for (const lower of ways) {
        if (lower.order >= upper.order) continue;
        for (const over of Bridges.segments(upper.points)) {
          for (const under of Bridges.segments(lower.points)) {
            const at = Bridges.cross(over, under);
            if (at) hits.push({ over: upper.order, flat: over.flat, at });
          }
        }
      }
    }
    return Bridges.together(hits);
  }

  static NEAR = 80;

  static together(hits) {
    const marks = [];
    for (const hit of hits) {
      const near = marks.find((mark) => mark.over === hit.over && mark.flat === hit.flat
        && hit.at.x >= mark.from.x - Bridges.NEAR && hit.at.x <= mark.to.x + Bridges.NEAR
        && hit.at.y >= mark.from.y - Bridges.NEAR && hit.at.y <= mark.to.y + Bridges.NEAR);
      if (!near) {
        marks.push({ over: hit.over, flat: hit.flat, from: { ...hit.at }, to: { ...hit.at } });
        continue;
      }
      near.from = { x: Math.min(near.from.x, hit.at.x), y: Math.min(near.from.y, hit.at.y) };
      near.to = { x: Math.max(near.to.x, hit.at.x), y: Math.max(near.to.y, hit.at.y) };
    }
    return marks;
  }

  static segments(points) {
    const found = [];
    for (let step = 0; step + 1 < points.length; step += 1) {
      const from = points[step];
      const to = points[step + 1];
      if (from.x === to.x && from.y === to.y) continue;
      found.push({ from, to, flat: from.y === to.y });
    }
    return found;
  }

  static cross(one, other) {
    if (one.flat === other.flat) return null;
    const flat = one.flat ? one : other;
    const upright = one.flat ? other : one;
    const between = (value, from, to) => value > Math.min(from, to) && value < Math.max(from, to);
    if (!between(upright.from.x, flat.from.x, flat.to.x)) return null;
    if (!between(flat.from.y, upright.from.y, upright.to.y)) return null;
    return { x: upright.from.x, y: flat.from.y };
  }

  /** The bridge deck: it covers the whole crossing, with room to spare for the lanes. */
  static MARGIN = 15;

  static deck(mark) {
    return {
      x: mark.from.x - Bridges.MARGIN,
      y: mark.from.y - Bridges.MARGIN,
      width: mark.to.x - mark.from.x + Bridges.MARGIN * 2,
      height: mark.to.y - mark.from.y + Bridges.MARGIN * 2,
      flat: mark.flat,
    };
  }
}

if (typeof module === 'object' && module.exports) module.exports = { Corridor, Bridges };

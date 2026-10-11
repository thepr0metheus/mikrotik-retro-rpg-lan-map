"""The picture of the network from one snapshot: castles, devices, and who lives in two.

Facts come from the snapshot, names and looks from the atlas. No name means we say so — a
name invented out of an address would look like a fact without being one.

Two addresses are counted as one device only when that is plain to see: either the atlas says
so, or the name occurs exactly once in each of two different networks. Five phones all called
"iPhone" inside one castle never merge into one device.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from typing import ClassVar

from .atlas import Atlas
from .tongue import Said

#: How a device made itself known. Codes: the words for them live in the dictionary.
LEASE, ARP, PEER, NETMAP = "lease", "arp", "peer", "netmap"

#: The router writes a span as 1w2d03:04:05, as 1w2d3h4m5s, or as plain 00:00:16 — the menu
#: decides, not the value. Both ways are read here, and only one of them is ever written back.
SPAN = re.compile(r"(\d+)([wdhms])")
CLOCK = re.compile(r"(\d+):(\d+):(\d+)")
UNITS = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}


def seconds(span: str):
    """How long ago the router says that was. None means it does not say at all."""
    text = str(span).strip()
    if not text:
        return None
    count = 0
    clock = CLOCK.search(text)
    if clock:
        hours, minutes, rest = (int(one) for one in clock.groups())
        count = hours * 3600 + minutes * 60 + rest
        text = text[:clock.start()]
    return count + sum(int(number) * UNITS[unit] for number, unit in SPAN.findall(text))


def spell(count) -> str:
    """A span written the one way the map writes them: the two largest units, no more."""
    if count is None:
        return ""
    said, left = [], int(count)
    for unit, size in UNITS.items():
        if left >= size:
            said.append(f"{left // size}{unit}")
            left %= size
    return "".join(said[:2]) or "0s"


def shift(ip: str, source: str, target: str) -> str:
    """The same host in another range: netmap keeps the host part and changes the network.

    Only between ranges of the same size — 192.168.216.3 out of a /24 into a /24 is
    192.168.100.3, and there is nothing to guess. Netmap between ranges of different sizes
    means something else, and the map says nothing rather than something made up."""
    try:
        one = ip_address(ip)
        from_range = ip_network(source, strict=False)
        to_range = ip_network(target, strict=False)
    except ValueError:
        return ""
    if one not in from_range or from_range.num_addresses != to_range.num_addresses:
        return ""
    return str(to_range.network_address + (int(one) - int(from_range.network_address)))


def peer_address(allowed: str) -> str:
    """The one address a peer answers to.

    A peer may be allowed a whole range — that is a road to a network behind it, not a device.
    Then it is nobody in particular, and the map keeps quiet rather than draw a house for it."""
    for part in str(allowed).split(","):
        address, _, bits = part.strip().partition("/")
        if bits not in ("32", ""):
            continue
        try:
            one = ip_address(address)
        except ValueError:
            continue
        if one.version == 4:
            return str(one)
    return ""


def peer_name(comment: str, interface: str) -> str:
    """The name a human wrote on a peer, without the interface RouterOS puts in front of it.

    Back to Home names its peers "<interface> iPhone", and the interface is written across the
    map already — saying it twice in one caption tells nobody anything."""
    text = str(comment).strip()
    if not interface:
        return text
    if text.lower() == interface.lower():
        return ""    # the whole comment is the interface: this peer was never given a name
    if text.lower().startswith(f"{interface.lower()} "):
        return text[len(interface) + 1:].strip()
    return text


@dataclass(frozen=True)
class Segment:
    key: str            # the interface name: bridge_main, vlan20_lab
    title: str          # the atlas name, or the interface name when the atlas is silent
    network: str        # 192.168.88.0/24
    gateway: str        # the router's address in this network
    vlan: int | None
    trusted: bool
    #: The address is handed out dynamically: the network appears with the VPN and leaves with it.
    temporary: bool
    #: The interface lists this network belongs to: the firewall rules look at those.
    lists: tuple

    def holds(self, ip: str) -> bool:
        try:
            return ip_address(ip) in ip_network(self.network)
        except ValueError:
            return False


@dataclass(frozen=True)
class Seat:
    """A device's seat: its address inside one of the castles."""
    ip: str
    segment: str
    online: bool
    #: Where we learnt of it: a DHCP lease, the ARP table, the list of Wi-Fi clients.
    seen: tuple
    #: How long since we last met, in the router's own words: "1m36s", "never", "" — unknown.
    last: str = ""


@dataclass(frozen=True)
class Device:
    key: str            # the MAC when it is known, otherwise the address
    name: str           # "" means it has no name
    kind: str           # the atlas kind: nas, ups, printer…; "" is an ordinary house
    seats: tuple
    #: What the device calls itself. Only this name can make two addresses one device: a
    #: human is free to repeat a caption, so a caption proves nothing.
    calls: str = ""

    @property
    def online(self) -> bool:
        return any(seat.online for seat in self.seats)

    @property
    def segments(self) -> tuple:
        """Every castle where the device has a known address — old leases included."""
        return tuple(dict.fromkeys(seat.segment for seat in self.seats))

    @property
    def homes(self) -> tuple:
        """The castles where the device is online now. An old lease is not a home."""
        return tuple(dict.fromkeys(seat.segment for seat in self.seats if seat.online))

    @property
    def in_two_castles(self) -> bool:
        """Lives in two networks right now, and so stands in the yard of each.

        Old leases cannot say this: a phone that moved from Home to the guests left a record
        in both networks while living in one."""
        return len(self.homes) > 1


@dataclass(frozen=True)
class Outpost:
    """The network beyond the gate: the one the house goes out through.

    It is never a castle. The rules there are not ours, we do not know who lives there and we
    cannot govern it — what is visible is exactly what can be seen from our side of the gate.
    It only appears when there is another private network out there: if that is the real
    internet, there is nothing to show.
    """
    interface: str
    network: str
    #: Our own address in that network.
    ours: str
    #: Who is in charge out there. Empty means the snapshot held no route table.
    gate: str
    #: Who else the router has seen there: ((address, MAC), ...).
    neighbours: tuple


@dataclass(frozen=True)
class Network:
    taken: str
    segments: tuple
    devices: tuple
    #: What stayed unclear: an address outside every network, and whatever else is said aloud.
    puzzles: tuple
    #: The network beyond the gate, when it is private. None means the internet starts there.
    outpost: object = None

    WAN_LIST: ClassVar[str] = "WAN"

    @classmethod
    def of(cls, snapshot, atlas: Atlas) -> "Network":
        builder = _Builder(snapshot, atlas)
        # Order matters: devices add to the puzzles, and the outpost looks at the same
        # interfaces — so it is worked out last, once everything else is read.
        segments, devices = builder.segments(), builder.devices()
        return cls(snapshot.taken, segments, devices, tuple(builder.puzzles), builder.outpost())


class _Builder:
    """One building of the picture: holds the snapshot, the atlas and the puzzles met on the way."""

    def __init__(self, snapshot, atlas: Atlas):
        self.snapshot = snapshot
        self.atlas = atlas
        self.puzzles: list = []
        self._segments = None

    # --- castles ------------------------------------------------------------------------------
    def segments(self) -> tuple:
        if self._segments is None:
            vlans = {row["name"]: int(row["vlan-id"]) for row in self.rows("interface/vlan")}
            lists = defaultdict(list)
            for row in self.rows("interface/list/member"):
                lists[row["interface"]].append(row["list"])
            found = []
            for row in self.rows("ip/address"):
                interface = row.get("actual-interface") or row["interface"]
                if row.get("disabled") == "true" or Network.WAN_LIST in lists.get(interface, []):
                    continue
                address, _, prefix = row["address"].partition("/")
                found.append(Segment(
                    key=interface, title=self.atlas.title(interface),
                    network=f"{row['network']}/{prefix}", gateway=address,
                    vlan=vlans.get(interface), trusted=self.atlas.trusted(interface),
                    temporary=row.get("dynamic") == "true", lists=tuple(lists.get(interface, ()))))
            self._segments = tuple(found)
        return self._segments

    def segment_of(self, ip: str, interface: str = "") -> str:
        """A device's castle: by interface when it is known, otherwise by address."""
        for segment in self.segments():
            if segment.key == interface or (not interface and segment.holds(ip)):
                return segment.key
        for segment in self.segments():  # the interface may belong elsewhere: the address decides
            if segment.holds(ip):
                return segment.key
        self.puzzles.append(Said.of("puzzle.stray-address", ip=ip))
        return ""

    # --- devices ------------------------------------------------------------------------------
    def devices(self) -> tuple:
        seats: dict = defaultdict(list)          # device key → seats and how sure we are
        names: dict = {}                         # device key → the name to show
        calls: dict = {}                         # device key → what it calls itself
        for ip, interface, online, mac, name, seen, sure, last, self_name in self.sightings():
            segment = self.segment_of(ip, interface)
            if not segment:
                continue
            key = mac or ip
            seats[key].append((Seat(ip, segment, online, (seen,), last), sure))
            # The router may show this address to the rest of the network as another one. Then
            # the device stands in two networks at once — where it lives, and where it is seen
            # — and the map draws both and says which is which.
            for shown in self.netmapped(ip, segment):
                where = self.segment_of(shown, "")
                if where:
                    seats[key].append((Seat(shown, where, online, (NETMAP,), last), sure))
            if name and not names.get(key):
                names[key] = name
            if self_name and not calls.get(key):
                calls[key] = self_name
        devices = [self.device(key, names.get(key, ""), self.settled(places), calls.get(key, ""))
                   for key, places in seats.items()]
        return tuple(sorted(self.join(devices), key=lambda device: (device.segments, device.key)))

    @staticmethod
    def settled(places: list) -> list:
        """A trace of a move is not yet a second home.

        An ARP record marked "stale" the router itself counts as not fresh: seen once, unsure
        now. While there is no other home we believe it — the device may simply be quiet. But
        if the same device is confirmed in another castle, the stale record is a memory of a
        former address, and it no longer counts as living there."""
        firm = {seat.segment for seat, sure in places if seat.online and sure}
        if not firm:
            return [seat for seat, _ in places]
        return [seat if sure or seat.segment in firm
                else Seat(seat.ip, seat.segment, False, seat.seen, seat.last)
                for seat, sure in places]

    def sightings(self):
        """Every sighting of a device: a lease, an ARP record, a VPN peer. One is seen twice."""
        yield from self.peers()
        servers = {row["name"]: row["interface"] for row in self.rows("ip/dhcp-server")}
        by_ip = self.dns_names()
        for row in self.rows("ip/dhcp-server/lease"):
            ip = row.get("active-address") or row.get("address", "")
            if not ip:
                continue
            # The caption on a lease outweighs the name a device reports for itself: a human
            # wrote the caption on purpose, while a phone changes its host-name when it likes.
            calls = row.get("host-name") or by_ip.get(ip, "")
            name = row.get("comment") or calls
            yield (ip, servers.get(row.get("server", ""), ""), row.get("status") == "bound",
                   (row.get("mac-address") or row.get("active-mac-address") or "").upper(), name,
                   LEASE, True, row.get("last-seen", ""), calls)
        online_macs = {row.get("mac-address", "").upper() for row in self.wifi()}
        outside = self.wan_interfaces()
        for row in self.rows("ip/arp"):
            ip = row.get("address", "")
            mac = (row.get("mac-address") or "").upper()
            if not ip or row.get("interface", "") in outside:
                continue  # a neighbour on the provider's side is no device of this house
            if row.get("status") in ("failed", "incomplete"):
                continue  # the router asked and nobody answered: a record of a question, not a dweller
            # "stale" means the router saw it once and has not asked again since. By itself
            # that does not put the device here: either a fresh answer or the Wi-Fi list must
            # confirm it. Otherwise a guest who left goes on living in the castle as a memory.
            fresh = row.get("status", "") != "stale"
            yield (ip, row.get("interface", ""),
                   (row.get("complete") == "true" and fresh) or mac in online_macs,
                   mac, by_ip.get(ip, ""), ARP, fresh, "", by_ip.get(ip, ""))

    #: How long after a handshake a peer still counts as connected. WireGuard speaks up every
    #: couple of minutes while it carries anything, so a longer silence is a tunnel standing
    #: open and idle — which is not the same as somebody being there.
    QUIET: ClassVar[int] = 180
    WIREGUARD: ClassVar[str] = "interface/wireguard/peers"

    def peers(self):
        """Whoever is connected over WireGuard right now.

        They have no lease and no ARP record, and that is not an oversight: a tunnel is not an
        Ethernet segment, so nothing hands out an address there and nobody answers a broadcast.
        The router knows them only as peers — and without this a phone on the VPN stands on
        nobody's map at all, while the network it is in is drawn and empty."""
        if self.WIREGUARD in self.snapshot.missing:
            return
        for row in self.snapshot.tables.get(self.WIREGUARD, []):
            if row.get("disabled") == "true":
                continue
            interface = row.get("interface", "")
            ip = peer_address(row.get("allowed-address", ""))
            if not ip:
                continue
            quiet = seconds(row.get("last-handshake", ""))
            yield (ip, interface, quiet is not None and quiet <= self.QUIET, "",
                   peer_name(row.get("comment", ""), interface), PEER, True, spell(quiet), "")

    NAT: ClassVar[str] = "ip/firewall/nat"

    def netmapped(self, ip: str, segment: str) -> list:
        """The addresses the router shows this one as to the rest of the network.

        A srcnat netmap rule maps a whole range onto another one one-to-one, so a phone on the
        VPN leaves the tunnel wearing an address from a network it has never been in. Everyone
        else sees that address, and looks for the phone there — which is exactly where the map
        had nothing to show.

        Only a rule naming one interface is read. A rule that picks its traffic by an interface
        list, or by anything else, may or may not touch this address, and a map that guesses is
        worse than a map that keeps quiet."""
        shown = []
        for row in self.snapshot.tables.get(self.NAT, []):
            if row.get("action") != "netmap" or row.get("chain") != "srcnat":
                continue
            if row.get("disabled") == "true" or row.get("in-interface") != segment:
                continue
            source = next((one.network for one in self.segments() if one.key == segment), "")
            mapped = shift(ip, row.get("src-address") or source, row.get("to-addresses", ""))
            if mapped and mapped not in shown:
                shown.append(mapped)
        return shown

    # --- what lies beyond the gate ----------------------------------------------------------------
    def outpost(self):
        """The network the house goes out through — if that one is private too."""
        wan = self.wan_interfaces()
        mine = None
        for row in self.rows("ip/address"):
            interface = row.get("actual-interface") or row["interface"]
            if interface not in wan or row.get("disabled") == "true":
                continue
            address, _, prefix = row["address"].partition("/")
            try:
                if not ip_address(address).is_private:
                    continue          # the real internet is out there: no outpost to show
            except ValueError:
                continue
            mine = (interface, f"{row['network']}/{prefix}", address)
            break
        if not mine:
            return None
        interface, network, ours = mine
        seen = {(row.get("address", ""), (row.get("mac-address") or "").upper())
                for row in self.rows("ip/arp")
                if row.get("interface") in wan and row.get("address") and row["address"] != ours}
        return Outpost(interface, network, ours, self.gate(), tuple(sorted(seen)))

    def gate(self) -> str:
        """Who is in charge beyond the gate. There may be no route table — then we keep quiet."""
        for row in self.snapshot.tables.get("ip/route", []):
            if row.get("dst-address") == "0.0.0.0/0" and row.get("gateway"):
                return row["gateway"].split("%")[0].strip()
        return ""

    def wan_interfaces(self) -> frozenset:
        """The interfaces facing out: whatever is behind them is no longer our network."""
        return frozenset(row["interface"] for row in self.rows("interface/list/member")
                         if row["list"] == Network.WAN_LIST)

    def wifi(self) -> list:
        """Wi-Fi clients. No table, no conclusion: we stay silent rather than say "nobody"."""
        if "interface/wifi/registration-table" in self.snapshot.missing:
            self.puzzles.append(Said.of(
                "puzzle.no-wifi",
                why=self.snapshot.missing["interface/wifi/registration-table"]))
            return []
        return self.rows("interface/wifi/registration-table")

    def dns_names(self) -> dict:
        names = {}
        for row in self.rows("ip/dns/static"):
            if row.get("address") and row.get("name") and row["address"] not in names:
                names[row["address"]] = row["name"]
        return names

    def device(self, key: str, name: str, seats: list, calls: str = "") -> Device:
        known = self.atlas.device(key, *(seat.ip for seat in seats))
        merged: dict = {}
        for seat in seats:
            same = merged.get(seat.ip)
            merged[seat.ip] = Seat(seat.ip, seat.segment, seat.online or (same.online if same else False),
                                   tuple(dict.fromkeys((same.seen if same else ()) + seat.seen)),
                                   seat.last or (same.last if same else ""))
        return Device(key=key, name=known.get("name", name), kind=known.get("kind", ""),
                      seats=tuple(merged.values()), calls=calls)

    # --- the same one in two castles --------------------------------------------------------------
    def join(self, devices: list) -> list:
        """Merges the records that are known for certain to be one device."""
        groups = self.named_once_per_segment(devices)
        groups += [tuple(sorted(group)) for group in self.atlas.same]
        by_ip = {seat.ip: device for device in devices for seat in device.seats}
        joined, taken = [], set()
        for group in groups:
            parts = [by_ip[ip] for ip in group if ip in by_ip and by_ip[ip].key not in taken]
            if len(parts) < 2:
                continue
            taken.update(part.key for part in parts)
            seats = tuple(seat for part in parts for seat in part.seats)
            # The name comes from whoever is online: when one self-given name has glued
            # today's thing to a memory of yesterday's, today's is the one to speak of.
            parts.sort(key=lambda part: not part.online)
            first = parts[0]
            joined.append(Device(first.key, first.name or next((p.name for p in parts if p.name), ""),
                                 first.kind or next((p.kind for p in parts if p.kind), ""), seats,
                                 first.calls))
        return joined + [device for device in devices if device.key not in taken]

    @staticmethod
    def named_once_per_segment(devices: list) -> list:
        """A self-given name seen at most once per castle belongs to a single device.

        It is the self-given name, not the caption: a human may hand the same caption to two
        different things, and they must not glue together because of it."""
        by_name = defaultdict(list)
        for device in devices:
            if device.calls and len(device.segments) == 1:
                by_name[device.calls].append(device)
        groups = []
        for name, found in by_name.items():
            segments = [device.segments[0] for device in found]
            if len(found) > 1 and len(set(segments)) == len(segments):
                groups.append(tuple(device.seats[0].ip for device in found))
        return groups

    def rows(self, path: str) -> list:
        return self.snapshot.rows(path)

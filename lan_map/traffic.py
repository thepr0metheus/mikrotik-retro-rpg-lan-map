"""Who is walking right now: the live connections the router holds in memory.

Roads answer the question "who may call". This is about who is calling: carts will roll along
the roads, and it will be plain which of them are used and which stand empty.

Held in memory is not the same as walking, though. The router forgets an established TCP
connection only a whole day after its last packet, so the table is full of journeys whose
traveller went home long ago. Whether somebody is here the map decides once, by the seats;
a connection of a device that is known to have left is not a walk, whatever the table keeps.

A connection inside one castle the router does not see at all — it goes past him. So it is not
here either: the map shows what the router knows and keeps quiet about what he cannot.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import ClassVar

from .memory import Memory
from .roads import INTERNET, ROUTER, SHOUT
from .spans import Space, Unclear
from .tongue import Said


@dataclass(frozen=True)
class Traffic:
    #: (from, to) → how many connections
    counts: dict
    #: (from, to) → {address: how many connections}. Who exactly rides this road.
    travellers: dict = field(default_factory=dict)
    #: address → {(to, road, port, protocol): how many}. Where each one walks, by live
    #: connections, and which end of which road that address turned out to be.
    trips: dict = field(default_factory=dict)
    #: address → the name the router himself last resolved to it.
    names: dict = field(default_factory=dict)
    #: Why there is no connection table. Empty means there is one.
    missing: object = ""
    #: The names he gave before and his cache has since let go of.
    memory: Memory = field(default_factory=Memory)

    TABLE: ClassVar[str] = "ip/firewall/connection"

    @classmethod
    def of(cls, snapshot, network, memory: Memory | None = None) -> "Traffic":
        if cls.TABLE in snapshot.missing:
            return cls({}, missing=Said.of("traffic.no-table", why=snapshot.missing[cls.TABLE]))
        if cls.TABLE not in snapshot.tables:
            return cls({}, missing=Said.of("traffic.not-taken"))
        homes = [(segment.key, Space.addresses(segment.network)) for segment in network.segments]
        # The router's own addresses, so that talking to him is not mistaken for walking into
        # the network he stands in. Every one of them lives inside a castle's range.
        gates = {segment.gateway for segment in network.segments if segment.gateway}
        gone = cls.gone(network.devices)
        counts: Counter = Counter()
        travellers: dict = {}
        trips: dict = {}
        for row in snapshot.rows(cls.TABLE):
            where = cls.address(row, "src")
            there = cls.address(row, "dst")
            # A phone that dropped off the VPN an hour ago leaves its Telegram connections
            # behind in the table for another day. Drawn, they ride to the sea while the
            # phone's own castle, rightly, stands empty — and the map argues with itself.
            if where in gone or there in gone:
                continue
            source = cls.where(where, homes, gates)
            target = cls.where(there, homes, gates)
            if not source or not target:
                continue
            # A walk inside one's own castle the router does not see; when he does, it counts.
            trips.setdefault(where, Counter())[
                (there, target, cls.port(row), row.get("protocol", ""))] += 1
            # A walk with nobody at the far end is no journey: a shout is still a walk, and
            # still worth showing next to the one who shouts, but there is no road to draw.
            if source == target or SHOUT in (source, target):
                continue
            counts[(source, target)] += 1
            travellers.setdefault((source, target), Counter())[where] += 1
        return cls(dict(counts), {pair: dict(who) for pair, who in travellers.items()},
                   {ip: dict(where) for ip, where in trips.items()}, cls.named(snapshot),
                   memory=memory or Memory())

    @staticmethod
    def gone(devices) -> frozenset:
        """The addresses the map knows, and knows to stand empty now.

        An address the map has never seen is not gone: it is unknown, and a connection from
        it is shown as the router reports it. Only a known absence silences a connection."""
        present: dict = {}
        for device in devices:
            for seat in device.seats:
                present[seat.ip] = present.get(seat.ip, False) or seat.online
        return frozenset(ip for ip, here in present.items() if not here)

    @classmethod
    def named(cls, snapshot) -> dict:
        """Who lives at each address, by the names the router resolved for us himself.

        He keeps a cache of every name the network asked him about, so a walk to
        17.248.213.65 can be read as a walk to Apple without the map asking anybody anything.
        Nothing is looked up here: what the router never resolved stays a bare number, and a
        device that does its own resolving is invisible to this on purpose."""
        if Memory.CACHE in snapshot.missing or Memory.CACHE not in snapshot.tables:
            return {}
        return Memory.resolved(snapshot.rows(Memory.CACHE))

    def called(self, address: str) -> dict:
        """An address's name: the router's answer now, or else the one he gave it before.

        The two are not equally sure, and the walk says which it carries: a name in his cache
        is a fact about this moment, a remembered one is what stood at that address lately."""
        if address in self.names:
            return {"name": self.names[address], "remembered": False}
        remembered = self.memory.name(address)
        return {"name": remembered, "remembered": bool(remembered)}

    @staticmethod
    def port(row: dict) -> str:
        """The destination port. The router writes it as its own field, or inside the address."""
        named = row.get("dst-port") or row.get("orig-dst-port") or ""
        if named:
            return str(named)
        text = row.get("dst-address") or row.get("orig-dst-address") or ""
        return text.partition(":")[2].strip()

    @staticmethod
    def address(row: dict, side: str) -> str:
        """The router writes the address with its port: 192.168.88.10:54321. We want the address."""
        text = row.get(f"{side}-address") or row.get(f"orig-{side}-address") or ""
        return text.split(":")[0].strip()

    #: The shout that belongs to no network at all. Multicast is asked about by its range.
    EVERYBODY: ClassVar[str] = "255.255.255.255"

    @classmethod
    def shouted(cls, address: str) -> bool:
        """Is this a shout to everybody at once — mdns, ssdp, a router calling for neighbours?

        A castle's own broadcast address is left to that castle on purpose: that is exactly
        where such a shout is heard, and the router sees it as a walk inside one yard."""
        if address == cls.EVERYBODY:
            return True
        try:
            return ip_address(address).is_multicast
        except ValueError:
            return False

    @classmethod
    def where(cls, address: str, homes, gates=()) -> str:
        """Whose address this is: nobody's, the router's own, a castle's, or the world's.

        A shout comes first: 224.0.0.251 is no more a place in the sea than 255.255.255.255
        is, and taken for one it would send a cart out over the water to meet nobody.

        Then the router. His address lies inside a castle's range — 192.168.88.1 is part of
        192.168.88.0/24 — so by range alone he would pass for one of that castle's dwellers,
        and a conversation with the customs house would be drawn as a journey into the town
        behind it. Empty means the address could not be read."""
        if not address:
            return ""
        if cls.shouted(address):
            return SHOUT
        if address in gates:
            return ROUTER
        try:
            one = Space.addresses(address)
        except Unclear:
            return ""
        for key, space in homes:
            if one.overlaps(space):
                return key
        return INTERNET

    #: How many riders we name: two or three carts ride a road anyway.
    MOST: ClassVar[int] = 3

    def rows(self) -> list:
        return [{"from": source, "to": target, "count": count, "who": self.who(source, target)}
                for (source, target), count in sorted(self.counts.items(), key=lambda pair: -pair[1])]

    #: How many walks we name per address: the scroll must not turn into a bedsheet.
    WALKS: ClassVar[int] = 12

    def walks(self, ip: str) -> list:
        """Where this address walks right now, the most frequent first.

        Each walk carries the end of the road it belongs to, the same key the carts ride
        between. Whoever asks "what does this cart carry" has already been told the road;
        working the castle out again from the address would be the same answer twice, and
        the page has no business guessing at ranges."""
        found = self.trips.get(ip, {})
        best = sorted(found.items(), key=lambda pair: (-pair[1], pair[0]))[:self.WALKS]
        return [{"to": where, **self.called(where), "where": road,
                 "port": port, "protocol": protocol, "count": count}
                for (where, road, port, protocol), count in best]

    def who(self, source: str, target: str) -> list:
        """Who rides this road, the most talkative first. A cart takes its name from this list."""
        found = self.travellers.get((source, target), {})
        best = sorted(found.items(), key=lambda pair: (-pair[1], pair[0]))[:self.MOST]
        return [{"ip": ip, "count": count} for ip, count in best]

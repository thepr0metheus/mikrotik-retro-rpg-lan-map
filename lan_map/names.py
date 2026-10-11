"""The names the router answers itself: its static DNS records, and where each of them leads.

Every network's DHCP hands its devices a DNS server. Where that server is the router, the
devices ask it for every name, and a static record is what makes a name such as
git.lan.example mean something at home. No other box in the network answers names, so the
router's list is the whole list.

The page of names shows those records as the router holds them — nothing on it is typed by
hand — grouped by the answer they give, and says for each answer who on the map holds it: the
router, a device, or nobody. Nobody is said out loud rather than passed over: the device may be
switched off and hold no lease, or be gone and have left its name behind.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Record:
    """One static record, in the router's own words."""

    #: The name it answers for; for a pattern record, the pattern itself.
    name: str
    #: A, AAAA, CNAME, FWD, TXT…: the router's type.
    kind: str
    #: What it answers with: an address, a name, a server, a text. "" when the map does not
    #: know where the router keeps that type's answer.
    to: str
    ttl: str
    comment: str
    disabled: bool
    #: A regular expression rather than one name: it answers for every name it matches.
    pattern: bool
    #: It answers for the name and for every name under it.
    subdomains: bool

    #: Where the router keeps each type's answer. A type missing here is shown without one:
    #: the map does not guess which field would hold it.
    ANSWERS: ClassVar[dict] = {"A": "address", "AAAA": "address", "CNAME": "cname",
                               "FWD": "forward-to", "TXT": "text", "MX": "mx-exchange",
                               "NS": "ns", "SRV": "srv-target"}
    #: The types that answer with an address: only those lead to somebody on the map.
    ADDRESSES: ClassVar[frozenset] = frozenset({"A", "AAAA"})
    #: A record without a type is an A record: RouterOS 6 had no other kind, and 7 still
    #: calls A the default.
    PLAIN: ClassVar[str] = "A"

    @classmethod
    def of(cls, row: dict) -> "Record":
        kind = (row.get("type") or cls.PLAIN).upper()
        answer = cls.ANSWERS.get(kind, "")
        return cls(name=row.get("name") or row.get("regexp", ""), kind=kind,
                   to=row.get(answer, "") if answer else "",
                   ttl=row.get("ttl", ""), comment=row.get("comment", ""),
                   disabled=row.get("disabled") == "true",
                   pattern=not row.get("name") and bool(row.get("regexp")),
                   subdomains=row.get("match-subdomain") == "true")

    @property
    def leads_home(self) -> bool:
        """It answers with an address, so somebody on the map may hold it."""
        return self.kind in self.ADDRESSES and bool(self.to)

    def payload(self) -> dict:
        return {"name": self.name, "type": self.kind, "ttl": self.ttl, "comment": self.comment,
                "disabled": self.disabled, "pattern": self.pattern, "subdomains": self.subdomains}


@dataclass(frozen=True)
class Place:
    """One answer the router gives, whoever the map finds holding it, and every name that gives it."""

    to: str
    #: One of Holders.WHERE.
    where: str
    #: The device's name. "" for the router, for nobody, for what is not an address, and for a
    #: device that has no name — the page says which of those it is.
    who: str
    #: The title of the network the address stands in; "" when it stands in none of them.
    segment: str
    records: tuple

    def payload(self) -> dict:
        return {"to": self.to, "where": self.where, "who": self.who, "segment": self.segment,
                "names": [record.payload() for record in self.records]}


@dataclass(frozen=True)
class Asker:
    """A network whose DHCP hands its devices DNS servers: whom those devices ask for names."""

    network: str
    #: The title of the castle that network is; "" when no castle is.
    segment: str
    servers: tuple
    #: True: every server handed out is the router. False: at least one is not, and the
    #: devices asking it do not get the router's names. None: DHCP hands out none here.
    router: bool | None

    def payload(self) -> dict:
        return {"network": self.network, "segment": self.segment, "servers": list(self.servers),
                "router": self.router}


@dataclass(frozen=True)
class Holders:
    """Who holds an address, as far as the map knows: the router, a device, or nobody."""

    #: The router's own addresses, every interface's.
    router: frozenset
    #: address → (device, seat)
    seats: dict
    segments: tuple

    #: The ways an answer is held. `beyond` is an answer that is not an address at all.
    WHERE: ClassVar[tuple] = ("router", "device", "nobody", "beyond")

    @classmethod
    def of(cls, snapshot, network) -> "Holders":
        own = frozenset(row["address"].partition("/")[0] for row in snapshot.rows("ip/address")
                        if row.get("disabled") != "true")
        return cls(own, {seat.ip: (device, seat) for device in network.devices
                         for seat in device.seats}, network.segments)

    def place(self, to: str, records: tuple) -> Place:
        if not records[0].leads_home:
            return Place(to, "beyond", "", "", records)
        if to in self.router:
            return Place(to, "router", "", self.around(to), records)
        if to in self.seats:
            device, seat = self.seats[to]
            return Place(to, "device", device.name, self.title(seat.segment), records)
        return Place(to, "nobody", "", self.around(to), records)

    def asker(self, row: dict) -> Asker:
        network = row.get("address", "")
        servers = tuple(server.strip() for server in row.get("dns-server", "").split(",")
                        if server.strip())
        return Asker(network, self.around(network.partition("/")[0]), servers,
                     all(server in self.router for server in servers) if servers else None)

    def title(self, key: str) -> str:
        return next((segment.title for segment in self.segments if segment.key == key), "")

    def around(self, ip: str) -> str:
        """The castle an address stands in, by the address alone."""
        return next((segment.title for segment in self.segments if segment.holds(ip)), "")


@dataclass(frozen=True)
class Names:
    places: tuple = ()
    askers: tuple = ()

    #: The table the names come from. It is not one of Snapshot.OPTIONAL: a snapshot the router
    #: would not give it to is never taken, so an empty list here is the router's own answer.
    TABLE: ClassVar[str] = "ip/dns/static"

    @classmethod
    def of(cls, snapshot, network) -> "Names":
        holders = Holders.of(snapshot, network)
        answers: dict = {}
        for row in snapshot.rows(cls.TABLE):
            record = Record.of(row)
            # An address and a name never collide: they are kept apart all the same, so that a
            # CNAME whose target looks like an address is never taken for a house.
            answers.setdefault((record.leads_home, record.to), []).append(record)
        places = [holders.place(to, tuple(sorted(records, key=lambda record: record.name.lower())))
                  for (_, to), records in answers.items()]
        # The answer with the most names first: that is where the network's services live.
        places.sort(key=lambda place: (-len(place.records), place.to))
        return cls(tuple(places),
                   tuple(holders.asker(row) for row in snapshot.rows("ip/dhcp-server/network")))

    def payload(self) -> dict:
        return {"places": [place.payload() for place in self.places],
                "askers": [asker.payload() for asker in self.askers]}

"""Where the house goes: the far ends of the live walks, named wherever that can be done.

The services page shows this and nothing else: who is known and how, and who is not known at
all. Nothing on it is typed by hand — every name comes from the router's own answers, now or
remembered, or from the map's table of houses. What none of them can name is listed as
exactly that, and never passed over.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import ClassVar

from .overseas import Overseas
from .roads import INTERNET


@dataclass(frozen=True)
class Destinations:
    #: (who, how it is known, connections, distinct addresses), the busiest first.
    known: tuple = ()
    #: (address, connections), the busiest first.
    unknown: tuple = ()

    #: The ways of knowing, the surest first. A line says the surest one among its walks.
    SURE: ClassVar[tuple] = ("name", "memory", "block")
    #: How many unknown addresses the page is handed. Beyond that it is a log, not a list.
    UNKNOWN_MOST: ClassVar[int] = 40

    @classmethod
    def of(cls, walks: dict) -> "Destinations":
        """From the picture's walks: a source address → the walks it makes."""
        count: Counter = Counter()
        unknown: Counter = Counter()
        how: dict = {}
        where: dict = {}
        for trips in walks.values():
            for trip in trips:
                if trip.get("where") != INTERNET:
                    continue        # an address at home is named by whoever lives at it
                many = trip.get("count", 1)
                who, known_by = cls.called(trip)
                if not who:
                    unknown[trip["to"]] += many
                    continue
                count[who] += many
                how[who] = min(how.get(who, known_by), known_by, key=cls.SURE.index)
                where.setdefault(who, set()).add(trip["to"])
        busiest = sorted(count, key=lambda who: (-count[who], who.lower()))
        return cls(tuple((who, how[who], count[who], len(where[who])) for who in busiest),
                   tuple(sorted(unknown.items(), key=lambda pair: (-pair[1], pair[0]))
                         [:cls.UNKNOWN_MOST]))

    @staticmethod
    def called(trip: dict) -> tuple:
        """Who a walk goes to and how that is known; ("", "") when nothing knows.

        In the order the map itself signs a walk. A house named by a name, now or remembered,
        comes first: "YouTube" rather than a CDN's hostname. Then the name alone, grouped by
        the domain somebody registered, so that a hundred hostnames of one service make one
        line. The house guessed from the block comes last: a name was given to this very
        address, the block only to the street it stands in."""
        if trip.get("house") and trip.get("by") in ("name", "memory"):
            return trip["house"], trip["by"]
        if trip.get("name"):
            return Overseas.domain(trip["name"]), "memory" if trip.get("remembered") else "name"
        if trip.get("house"):
            return trip["house"], "block"
        return "", ""

    def payload(self) -> dict:
        return {"known": [{"who": who, "by": by, "count": count, "addresses": addresses}
                          for who, by, count, addresses in self.known],
                "unknown": [{"ip": ip, "count": count} for ip, count in self.unknown]}

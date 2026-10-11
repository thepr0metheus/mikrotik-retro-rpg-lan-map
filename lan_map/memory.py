"""The names the router once resolved, remembered past his cache.

The router answers a name and keeps the answer for minutes — a CDN's for one, a quiet
service's for an hour. The map looks into his cache when it takes a snapshot, and whatever
expired in between it never sees: the name is gone, the connection stays, and the address
walks the map as a bare number. So the map writes down what it saw: every address the router
resolved, the name, and when that was last seen.

Nothing is asked of anybody. These are the router's own answers, kept longer than he keeps
them himself.

A remembered name is a guess, not a fact, and the map says so. Addresses are re-let, and one
behind a CDN answers to a thousand sites. So a fresher reading wins over an older one, and a
name nobody has seen for two weeks is forgotten.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import ClassVar

from .snapshot import Snapshot


@dataclass(frozen=True)
class Memory:
    #: address → (name, when it was last seen: ISO, UTC, to the second)
    names: dict = field(default_factory=dict)

    #: How long a name is kept after it was last seen.
    DAYS: ClassVar[int] = 14
    #: The router's DNS cache: where every name comes from.
    CACHE: ClassVar[str] = "ip/dns/cache"
    #: Record types that answer with an address. A CNAME answers with another name.
    ADDRESSES: ClassVar[frozenset] = frozenset({"A", "AAAA"})

    @classmethod
    def resolved(cls, rows) -> dict:
        """address → name, from one reading of the router's DNS cache.

        One address answers to many names, so the shortest wins — `push.apple.com` tells a
        reader more than `use1-pp-st-vs-sc.push.apple.com`, and the choice must not wander
        between two readings of the same table."""
        names: dict = {}
        for row in rows:
            address, name = row.get("data", ""), row.get("name", "")
            if not address or not name or row.get("type", "A") not in cls.ADDRESSES:
                continue
            if address not in names or (len(name), name) < (len(names[address]), names[address]):
                names[address] = name
        return names

    def learned(self, rows, seen: str) -> "Memory":
        """This memory with one more reading of the cache in it, the one taken at `seen`.

        A fresher reading replaces an older one for the same address. An older one — a stored
        snapshot read again at start — changes nothing that is already fresher, so reading the
        same past twice is harmless."""
        names = dict(self.names)
        for address, name in self.resolved(rows).items():
            if address not in names or names[address][1] <= seen:
                names[address] = (name, seen)
        return Memory(names)

    def forgotten(self, now: datetime) -> "Memory":
        """Without the names nobody has seen for DAYS: whoever stood at the address may be gone."""
        edge = (now - timedelta(days=self.DAYS)).isoformat(timespec="seconds")
        return Memory({address: kept for address, kept in self.names.items() if kept[1] >= edge})

    def name(self, address: str) -> str:
        """The name the router last gave this address; empty when he never gave one."""
        kept = self.names.get(address)
        return kept[0] if kept else ""

    # --- on disk --------------------------------------------------------------------------------
    @classmethod
    def read(cls, path) -> "Memory":
        """No file is an empty memory: the map has only just begun to remember.

        A file that cannot be read is not an empty memory, and is not treated as one: the
        error goes to whoever called, who decides what to do with a memory lost."""
        path = Path(path)
        if not path.is_file():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls({str(address): (str(kept[0]), str(kept[1]))
                    for address, kept in payload["names"].items()})

    def write(self, path) -> Path:
        return Snapshot.lay(path, {"names": {address: list(kept)
                                             for address, kept in sorted(self.names.items())}})

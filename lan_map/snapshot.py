"""The snapshot: what the router said about the network at one moment in time.

Tables are kept exactly as the router gave them. Every conclusion — segments, devices, who
reaches whom — is drawn afterwards and only from the snapshot. So a wrong picture can always
be traced back to what the router actually said.

With one exception, named here so that it is never taken for an accident: secrets are not
kept. Private and preshared keys, passwords, passphrases draw nothing on the map, and on disk
they are a key to the house — the WireGuard peers table alone carries the private key of every
VPN client, and with it anyone walks in as that phone, with that phone's rights.

A table the router does not have is remembered separately, with the reason. "I do not know"
and "empty" look different on the map.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, ClassVar

from .routeros import RouterError
from .tongue import Tongue


@dataclass(frozen=True)
class Snapshot:
    #: When it was taken, UTC, in ISO form.
    taken: str
    #: table path → rows, as the router gave them
    tables: dict
    #: table path → why it is not here, as a phrase that has not chosen a language yet
    missing: dict

    #: Everything the map needs, in reading order.
    PATHS: ClassVar[tuple] = (
        "system/resource",
        "ip/address", "interface", "interface/vlan",
        "interface/bridge/port", "interface/bridge/vlan",
        "interface/list", "interface/list/member",
        "ip/dhcp-server", "ip/dhcp-server/network", "ip/dhcp-server/lease",
        "ip/arp", "ip/neighbor", "ip/dns/static", "ip/dns/cache", "ip/route",
        "interface/wifi/registration-table", "interface/wireguard/peers",
        "ip/firewall/filter", "ip/firewall/nat", "ip/firewall/address-list",
        "ip/firewall/raw", "ip/firewall/mangle", "ip/ipsec/policy",
        "ip/firewall/connection",
    )
    #: Parts of a field name that mark a secret. Parts rather than names, because the router
    #: spells one thing many ways: `private-key` on a peer, `vpn-private-key` in /ip cloud,
    #: `wpa2-pre-shared-key` on old Wi-Fi, `security.passphrase` on new.
    SECRETS: ClassVar[tuple] = ("private-key", "preshared-key", "pre-shared-key", "secret",
                                "password", "passphrase", "psk", "auth-key", "md5-key",
                                "static-key", "token")

    #: Tables the router may not have at all: a different Wi-Fi package, a different menu.
    #: Their absence is not a fault, and not emptiness either: the map says so.
    OPTIONAL: ClassVar[frozenset] = frozenset({
        "interface/wifi/registration-table", "interface/wireguard/peers",
        "ip/neighbor", "ip/route", "ip/dns/cache",
        "ip/firewall/raw", "ip/firewall/mangle", "ip/ipsec/policy",
        "ip/firewall/connection"})

    def __post_init__(self):
        # However a snapshot comes to be — taken from the router, read from disk, built by a
        # test — it holds no secrets from its first moment, so nothing written from it can.
        object.__setattr__(self, "tables", {path: self.unsecret(rows)
                                            for path, rows in self.tables.items()})

    @classmethod
    def secret(cls, field: str) -> bool:
        return any(part in field.lower() for part in cls.SECRETS)

    @classmethod
    def unsecret(cls, rows):
        """A table without its secrets. Most tables are rows; a few, like system/resource, one object."""
        if isinstance(rows, dict):
            return {field: value for field, value in rows.items() if not cls.secret(field)}
        return [cls.unsecret(row) if isinstance(row, dict) else row for row in rows]

    @classmethod
    def take(cls, rest, clock: Callable[[], datetime]) -> "Snapshot":
        tables, missing = {}, {}
        for path in cls.PATHS:
            try:
                tables[path] = rest.get(path)
            except RouterError as err:
                if path not in cls.OPTIONAL:
                    raise
                missing[path] = err.said.payload()
        return cls(clock().astimezone(timezone.utc).isoformat(timespec="seconds"), tables, missing)

    def rows(self, path: str) -> list:
        """A table's rows. A missing table is not asked for rows — look at `missing` first."""
        if path in self.missing:
            raise KeyError(f"{path}: not in this snapshot — {Tongue.of().tell(self.missing[path])}")
        return self.tables[path]

    def to_payload(self) -> dict:
        return {"taken": self.taken, "tables": self.tables, "missing": self.missing}

    @classmethod
    def from_payload(cls, payload: dict) -> "Snapshot":
        return cls(payload["taken"], payload["tables"], payload.get("missing", {}))

    def write(self, path: Path) -> Path:
        """All or nothing: the snapshot is written to a temporary file and replaces the last one.

        The last one is not thrown away but stepped aside: it is what "what changed" is against."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            path.replace(self.before(path))
        self.lay(path, self.to_payload())
        self.keep(path)
        return path

    @staticmethod
    def lay(path: Path, payload: dict) -> Path:
        """All or nothing: into a temporary file first, then into place in one step."""
        path = Path(path)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path

    @staticmethod
    def before(path: Path) -> Path:
        """Where the previous snapshot lies: "what changed" is worked out against it."""
        path = Path(path)
        return path.with_name(f"before-{path.name}")

    #: How many snapshots we keep in reserve. Past that, the oldest leave.
    KEEP: ClassVar[int] = 12

    @staticmethod
    def shelf(path: Path) -> Path:
        return Path(path).parent / "history"

    def keep(self, path: Path) -> Path:
        """A snapshot onto the shelf: from these the map can show how yesterday looked."""
        shelf = self.shelf(path)
        shelf.mkdir(parents=True, exist_ok=True)
        kept = shelf / f"{self.taken.replace(':', '-')}.json"
        self.lay(kept, self.to_payload())
        old = sorted(shelf.glob("*.json"))[:-self.KEEP]
        for gone in old:
            gone.unlink(missing_ok=True)
        return kept

    @classmethod
    def read(cls, path: Path) -> "Snapshot":
        return cls.from_payload(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def stored(cls, path: Path) -> list:
        """Every snapshot on disk: the current one, the one stepped aside, and the shelf."""
        path = Path(path)
        shelf = cls.shelf(path)
        kept = sorted(shelf.glob("*.json")) if shelf.is_dir() else []
        return [one for one in (path, cls.before(path), *kept) if one.is_file()]

    @classmethod
    def scrub(cls, path: Path) -> list:
        """Rewrite every stored snapshot that still holds secrets. Returns the ones rewritten.

        Snapshots written before secrets were dropped still carry them. Reading one strips
        them in memory; this puts the stripped one back in its place, so that the disk agrees."""
        done = []
        for one in cls.stored(path):
            payload = json.loads(one.read_text(encoding="utf-8"))
            clean = cls.from_payload(payload)
            if clean.tables != payload.get("tables"):
                cls.lay(one, {**payload, "tables": clean.tables})
                done.append(one)
        return done

    def counts(self) -> dict:
        """How many rows in each table — for the short report after a snapshot is taken.

        Not every table is a list: the router gives system/resource as a single object."""
        return {path: len(rows) if isinstance(rows, list) else 1 for path, rows in self.tables.items()}


def utc_now() -> datetime:
    """The real clock. Kept outside Snapshot so that tests can hand it their own."""
    return datetime.now(timezone.utc)

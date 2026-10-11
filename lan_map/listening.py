"""What listens on the map's host, from the kernel's own TCP tables, and the port a new app on
that host takes next.

The map lives in the host's network (`network_mode: host` in compose.yaml), so /proc/net in its
container is the host's: every listening socket of the NAS, Docker's and DSM's own included.
Only the numbers of listening ports are read. No address and no connection leaves this module,
and the ports themselves are shown nowhere: they only decide which port is free.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True)
class Listening:
    """The TCP ports something listens on, or why they are not known: then `ports` is None."""

    ports: frozenset | None
    #: Why the ports are not known, when they are not.
    missing: str = ""

    #: (table, may be absent): the IPv6 table is missing when IPv6 is off.
    TABLES: ClassVar[tuple] = (("tcp", False), ("tcp6", True))
    #: The state column of a listening socket.
    LISTEN: ClassVar[str] = "0A"

    @classmethod
    def read(cls, folder: Path | None) -> "Listening":
        """From the folder the kernel keeps its tables in: /proc/net on Linux, None elsewhere."""
        if folder is None:
            return cls(None, "free-port.no-tables")
        found = set()
        for name, optional in cls.TABLES:
            try:
                rows = (Path(folder) / name).read_text(encoding="ascii").splitlines()[1:]
            except FileNotFoundError:
                if optional:
                    continue
                return cls(None, "free-port.no-tables")
            except (OSError, UnicodeDecodeError):
                return cls(None, "free-port.unreadable")
            for row in rows:
                fields = row.split()
                if len(fields) < 4 or fields[3] != cls.LISTEN:
                    continue
                try:
                    found.add(int(fields[1].rsplit(":", 1)[1], 16))
                except (IndexError, ValueError):
                    return cls(None, "free-port.unreadable")
        return cls(frozenset(found))


#: Nobody asked the kernel: the answer says so rather than call every port free.
UNASKED = Listening(None, "free-port.no-tables")


@dataclass(frozen=True)
class FreePort:
    """The ports a new app on the NAS may take, in the order it takes them: 18150, 18160, …"""

    FIRST: ClassVar[int] = 18150
    STEP: ClassVar[int] = 10
    LAST: ClassVar[int] = 18990

    @classmethod
    def span(cls) -> dict:
        return {"first": cls.FIRST, "last": cls.LAST, "step": cls.STEP}

    @classmethod
    def first(cls, taken) -> int | None:
        """The first port not taken; None when every one is."""
        return next((port for port in range(cls.FIRST, cls.LAST + 1, cls.STEP) if port not in taken), None)

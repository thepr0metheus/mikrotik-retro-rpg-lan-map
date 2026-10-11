"""Runs of numbers: an address and a port are both numbers, and a condition is a set of runs.

They have to be counted exactly. "open to 192.168.40.107-192.168.40.108" and "open to the
whole network" look different on the map, and the difference comes from intersecting runs
rather than from a guess.
"""
from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network, summarize_address_range

from .tongue import Said

PORT_HIGH = 65535
ADDRESS_HIGH = 2 ** 32 - 1

#: What a set of addresses or ports is called when there is nothing to name. These are codes,
#: not words: the language they are said in is chosen much later, at the edge.
NOBODY = "nobody"
NO_PORTS = "no-ports"
ANY_PORT = "any-port"


class Unclear(ValueError):
    """A condition we did not understand. Better said out loud than counted by guesswork."""

    def __init__(self, said: Said):
        super().__init__(said.key)
        self.said = said


class Space:
    """A set of runs, closed at both ends. An empty set means "nothing matches"."""

    __slots__ = ("spans",)

    def __init__(self, spans=()):
        merged: list = []
        for low, high in sorted(tuple(span) for span in spans):
            if high < low:
                raise Unclear(Said.of("span.backwards", low=low, high=high))
            if merged and low <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], high)
            else:
                merged.append([low, high])
        self.spans = tuple((low, high) for low, high in merged)

    # --- how to get one -------------------------------------------------------------------------
    @classmethod
    def whole(cls, high: int = ADDRESS_HIGH) -> "Space":
        return cls([(0, high)])

    @classmethod
    def addresses(cls, text: str) -> "Space":
        """`192.168.88.200`, `192.168.20.0/24`, `192.168.40.107-192.168.40.108`, comma separated.

        `!192.168.88.0/24` means "everything but": the router reads it the same way."""
        if text.strip().startswith("!"):
            return cls.whole() - cls.addresses(text.strip()[1:])
        spans = []
        for part in cls._parts(text):
            if "-" in part:
                low, _, high = part.partition("-")
                spans.append((cls._ip(low), cls._ip(high)))
            elif "/" in part:
                network = cls._network(part)
                spans.append((int(network.network_address), int(network.broadcast_address)))
            else:
                spans.append((cls._ip(part), cls._ip(part)))
        return cls(spans)

    @classmethod
    def ports(cls, text: str) -> "Space":
        """`445`, `8100-8199`, `25565,25566`. Empty means any port, `!445` means any but that."""
        if not text.strip():
            return cls.whole(PORT_HIGH)
        if text.strip().startswith("!"):
            return cls.whole(PORT_HIGH) - cls.ports(text.strip()[1:])
        spans = []
        for part in cls._parts(text):
            low, _, high = part.partition("-")
            spans.append((cls._port(low), cls._port(high or low)))
        return cls(spans)

    @staticmethod
    def _parts(text: str) -> list:
        if "!" in text:
            raise Unclear(Said.of("span.negated", text=text))
        parts = [part.strip() for part in text.split(",")]
        if not all(parts):
            raise Unclear(Said.of("span.empty-part", text=text))
        return parts

    @staticmethod
    def _ip(text: str) -> int:
        try:
            return int(IPv4Address(text.strip()))
        except ValueError as error:
            raise Unclear(Said.of("span.not-address", text=text)) from error

    @staticmethod
    def _network(text: str) -> IPv4Network:
        try:
            return IPv4Network(text.strip(), strict=False)
        except ValueError as error:
            raise Unclear(Said.of("span.not-network", text=text)) from error

    @staticmethod
    def _port(text: str) -> int:
        try:
            number = int(text.strip())
        except ValueError as error:
            raise Unclear(Said.of("span.not-port", text=text)) from error
        if not 0 <= number <= PORT_HIGH:
            raise Unclear(Said.of("span.port-out-of-range", text=text))
        return number

    # --- how to count with one ------------------------------------------------------------------
    def __bool__(self) -> bool:
        return bool(self.spans)

    def __eq__(self, other) -> bool:
        return isinstance(other, Space) and self.spans == other.spans

    def __hash__(self) -> int:
        return hash(self.spans)

    def __repr__(self) -> str:
        return f"Space({list(self.spans)})"

    def __contains__(self, number: int) -> bool:
        return any(low <= number <= high for low, high in self.spans)

    def __and__(self, other: "Space") -> "Space":
        found = []
        for low, high in self.spans:
            for other_low, other_high in other.spans:
                start, stop = max(low, other_low), min(high, other_high)
                if start <= stop:
                    found.append((start, stop))
        return Space(found)

    def __or__(self, other: "Space") -> "Space":
        return Space(self.spans + other.spans)

    def __sub__(self, other: "Space") -> "Space":
        found = []
        for low, high in self.spans:
            pieces = [(low, high)]
            for other_low, other_high in other.spans:
                nextpieces = []
                for start, stop in pieces:
                    if other_high < start or other_low > stop:
                        nextpieces.append((start, stop))
                        continue
                    if start < other_low:
                        nextpieces.append((start, other_low - 1))
                    if other_high < stop:
                        nextpieces.append((other_high + 1, stop))
                pieces = nextpieces
            found += pieces
        return Space(found)

    def overlaps(self, other: "Space") -> bool:
        return bool(self & other)

    @property
    def size(self) -> int:
        return sum(high - low + 1 for low, high in self.spans)

    # --- how to cut one -------------------------------------------------------------------------
    def bounds(self) -> set:
        """Where a condition starts or ends: the space is cut along exactly these marks."""
        marks = set()
        for low, high in self.spans:
            marks.add(low)
            marks.add(high + 1)
        return marks

    def split(self, marks) -> list:
        """Pieces each of which every rule either sees whole or does not see at all."""
        pieces = []
        marks = sorted(marks)
        for low, high in self.spans:
            start = low
            for mark in marks:
                if start < mark <= high:
                    pieces.append(Space([(start, mark - 1)]))
                    start = mark
            pieces.append(Space([(start, high)]))
        return pieces

    # --- how to say one out loud ----------------------------------------------------------------
    def address_text(self) -> str:
        if not self.spans:
            return NOBODY
        parts = []
        for low, high in self.spans:
            parts.append(self._block(low, high))
        return ", ".join(parts)

    @staticmethod
    def _block(low: int, high: int) -> str:
        """A whole network is called a network, one address an address, a handful from-to.

        `192.168.20.10/31` is formally right, but it hides that these are two neighbours."""
        if low == high:
            return str(IPv4Address(low))
        blocks = list(summarize_address_range(IPv4Address(low), IPv4Address(high)))
        if len(blocks) == 1 and blocks[0].prefixlen <= 24:
            return str(blocks[0])
        return f"{IPv4Address(low)}-{IPv4Address(high)}"

    def ports_text(self) -> str:
        if not self.spans:
            return NO_PORTS
        if self.spans == ((0, PORT_HIGH),):
            return ANY_PORT
        return ", ".join(str(low) if low == high else f"{low}-{high}" for low, high in self.spans)

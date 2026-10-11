"""What changed since the last snapshot: who appeared, who vanished, which rules differ.

Two snapshots are kept: the fresh one and the one before. That is enough to answer "so what
changed?" and not enough to keep a chronicle — and no chronicle was promised.

Facts are compared, not pictures: devices by MAC, rules by their conditions. A rule that
merely moved one line up is not a change: the router does read the order, but the condition
stayed the same.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import ClassVar

from .atlas import Atlas
from .model import Network
from .tongue import Said


@dataclass(frozen=True)
class Changes:
    #: When the snapshot we compared against was taken; empty means there was nothing to compare.
    before: str
    lines: tuple

    #: The fields of a rule that decide its fate. The order of rules is not one of them.
    RULE: ClassVar[tuple] = (
        "chain", "action", "comment", "src-address", "dst-address", "src-address-list",
        "dst-address-list", "protocol", "dst-port", "in-interface", "out-interface",
        "in-interface-list", "out-interface-list", "connection-state", "disabled")

    @classmethod
    def between(cls, before, after, atlas: Atlas | None = None) -> "Changes":
        if before is None:
            return cls("", ())
        atlas = atlas or Atlas.empty()
        lines = cls.castles(before, after, atlas) + cls.houses(before, after, atlas) \
            + cls.rules(before, after)
        return cls(before.taken, tuple(lines))

    @classmethod
    def castles(cls, before, after, atlas) -> list:
        was = {segment.key: segment.title for segment in Network.of(before, atlas).segments}
        now = {segment.key: segment.title for segment in Network.of(after, atlas).segments}
        lines = [Said.of("change.castle-came", title=title)
                 for key, title in now.items() if key not in was]
        return lines + [Said.of("change.castle-gone", title=title)
                        for key, title in was.items() if key not in now]

    @classmethod
    def houses(cls, before, after, atlas) -> list:
        was = {device.key: device for device in Network.of(before, atlas).devices}
        now = {device.key: device for device in Network.of(after, atlas).devices}
        lines = [Said.of("change.device-came", who=cls.name(device))
                 for key, device in now.items() if key not in was]
        lines += [Said.of("change.device-gone", who=cls.name(device))
                  for key, device in was.items() if key not in now]
        for key, device in now.items():
            older = was.get(key)
            if older and older.online and not device.online:
                lines.append(Said.of("change.went-offline", who=cls.name(device)))
            elif older and not older.online and device.online:
                lines.append(Said.of("change.came-online", who=cls.name(device)))
        return lines

    @staticmethod
    def name(device) -> Said:
        where = device.seats[0].ip if device.seats else device.key
        return (Said.of("change.named", name=device.name, where=where) if device.name
                else Said.of("change.nameless", where=where))

    @classmethod
    def rules(cls, before, after) -> list:
        was = Counter(cls.mark(row) for row in before.tables.get("ip/firewall/filter", []))
        now = Counter(cls.mark(row) for row in after.tables.get("ip/firewall/filter", []))
        lines = [Said.of("change.rule-new", rule=cls.said(mark)) for mark in (now - was).elements()]
        return lines + [Said.of("change.rule-gone", rule=cls.said(mark))
                        for mark in (was - now).elements()]

    @classmethod
    def mark(cls, row: dict) -> tuple:
        return tuple(row.get(field, "") for field in cls.RULE)

    @classmethod
    def said(cls, mark: tuple) -> Said:
        row = dict(zip(cls.RULE, mark))
        where = " \u2192 ".join(part for part in (row.get("src-address"), row.get("dst-address")) if part)
        return Said.of("change.rule", chain=row["chain"], action=row["action"],
                       comment=row.get("comment") or Said.of("change.uncaptioned"),
                       where=Said.of("change.rule-where", where=where) if where else "",
                       off=Said.of("change.rule-off") if row.get("disabled") == "true" else "")

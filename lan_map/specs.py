"""What a device is made of — its system, processor, memory and disks — as the owner or an agent
wrote it down.

The router knows none of this, and the map never guesses it: every line was typed by somebody,
and a card says who and when. Agents read it at /specs.md and /api/specs instead of asking the
owner again, and write it with PUT /api/specs.

One file, data/specs.json, beside the atlas: device key → card. The key is the map's own — the
MAC when the router saw one, otherwise the address — and a card is found by any of a device's
keys, as an atlas record is, so it stays with its device when the address changes.

The device's name is not on the card. It is the map's name, kept in the atlas: one fact, one
place. The card's page and PUT /api/specs may change it, and they change the atlas.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from .tongue import Said, Tongue


class CardRefused(ValueError):
    """A card that cannot be written, and why: a phrase waiting for a language."""

    def __init__(self, said: Said):
        super().__init__(said.key)
        self.said = said


@dataclass(frozen=True)
class Line:
    """One line a card may hold: its key, what it holds, and how much of it."""

    key: str
    #: text — one line; long — lines; count — a whole number from 1; size — gigabytes; disks
    kind: str
    #: the longest text, the largest number, the most disks
    most: int

    #: A disk's own lines: its size and what it is.
    DISK_TYPE_MOST: ClassVar[int] = 40
    DISK_MOST_GB: ClassVar[int] = 1_000_000

    def clean(self, value):
        """The value as kept, or None to wipe the line. Anything else is refused, said why."""
        if value is None or value == "" or value == []:
            return None
        return getattr(self, f"clean_{self.kind}")(value)

    def clean_text(self, value) -> str:
        if not isinstance(value, str) or len(" ".join(value.split())) > self.most:
            raise CardRefused(Said.of("refuse.specs-text", field=self.key, most=self.most))
        return " ".join(value.split()) or None

    def clean_long(self, value) -> str:
        if not isinstance(value, str) or len(value.strip()) > self.most:
            raise CardRefused(Said.of("refuse.specs-text", field=self.key, most=self.most))
        return "\n".join(line.rstrip() for line in value.strip().splitlines()) or None

    def clean_count(self, value) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= self.most:
            raise CardRefused(Said.of("refuse.specs-count", field=self.key, most=self.most))
        return value

    def clean_size(self, value, most=None):
        most = most or self.most
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= most:
            raise CardRefused(Said.of("refuse.specs-size", field=self.key, most=most))
        value = round(float(value), 3)
        return int(value) if value.is_integer() else value

    def clean_disks(self, value) -> list:
        refused = CardRefused(Said.of("refuse.specs-disks", most=self.most, type_most=self.DISK_TYPE_MOST))
        if not isinstance(value, list) or len(value) > self.most:
            raise refused
        disks = []
        for disk in value:
            if not isinstance(disk, dict) or set(disk) - {"size_gb", "type"} or "size_gb" not in disk:
                raise refused
            kind = disk.get("type") or ""
            if not isinstance(kind, str) or len(" ".join(kind.split())) > self.DISK_TYPE_MOST:
                raise refused
            try:
                size = self.clean_size(disk["size_gb"], self.DISK_MOST_GB)
            except CardRefused:
                raise refused from None
            disks.append({"size_gb": size, **({"type": " ".join(kind.split())} if kind.strip() else {})})
        return disks


@dataclass(frozen=True)
class Specs:
    """Every card written, by device key."""

    #: device key → the lines written, and when and by whom
    cards: dict = field(default_factory=dict)

    #: Everything a card may hold, in the order it is told.
    LINES: ClassVar[tuple] = (
        Line("model", "text", 120),
        Line("os", "text", 60),
        Line("os_version", "text", 60),
        Line("arch", "text", 20),
        Line("cpu", "text", 120),
        Line("cores", "count", 1024),
        Line("threads", "count", 4096),
        Line("ram_gb", "size", 65536),
        Line("ram_type", "text", 40),
        Line("gpu", "text", 120),
        Line("disks", "disks", 16),
        Line("role", "text", 200),
        Line("notes", "long", 2000),
    )
    #: Who wrote a card: a name, not a proof — anybody may sign as anybody.
    BY_MOST: ClassVar[int] = 60
    #: What the map itself writes beside the lines.
    STAMPS: ClassVar[tuple] = ("updated", "by")

    @classmethod
    def read(cls, path: Path) -> "Specs":
        """No file is no cards yet. A file that does not read raises: it is somebody's work."""
        path = Path(path)
        if not path.is_file():
            return cls()
        return cls(dict(json.loads(path.read_text(encoding="utf-8")).get("devices", {})))

    @classmethod
    def keys(cls) -> tuple:
        return tuple(line.key for line in cls.LINES)

    @classmethod
    def described(cls) -> list:
        """What a card holds, for whoever builds a form for it: the page builds its own from this."""
        return [{"key": line.key, "kind": line.kind, "most": line.most} for line in cls.LINES]

    def found(self, *keys: str) -> tuple:
        """(the key a card is kept under, the card), by any of a device's keys; ("", {}) for none."""
        for key in keys:
            if key and key in self.cards:
                return key, self.cards[key]
        return "", {}

    @classmethod
    def clean(cls, fields: dict) -> dict:
        """The lines as they will be kept; None wipes one. A line the card has no place for is
        refused rather than dropped: whoever sent it would believe it was written."""
        lines = {line.key: line for line in cls.LINES}
        unknown = sorted(set(fields) - set(lines))
        if unknown:
            raise CardRefused(Said.of("refuse.specs-unknown-field", field=unknown[0], fields=", ".join(lines)))
        return {name: lines[name].clean(value) for name, value in fields.items()}

    @classmethod
    def signed(cls, by) -> str:
        if by is None or by == "":
            return ""
        if not isinstance(by, str) or len(" ".join(by.split())) > cls.BY_MOST:
            raise CardRefused(Said.of("refuse.specs-by", most=cls.BY_MOST))
        return " ".join(by.split())

    def with_card(self, keys: tuple, fields: dict, by: str, now: str) -> "Specs":
        """The cards with one device's card changed: named lines set, empty ones wiped, the rest
        kept. The card moves to the device's first key; a card left with no lines is dropped."""
        clean, signed = self.clean(fields), self.signed(by)
        kept_under, card = self.found(*keys)
        lines = {name: value for name, value in card.items() if name not in self.STAMPS}
        for name, value in clean.items():
            if value is None:
                lines.pop(name, None)
            else:
                lines[name] = value
        cards = {key: dict(entry) for key, entry in self.cards.items() if key != kept_under}
        if lines:
            ordered = {line.key: lines[line.key] for line in self.LINES if line.key in lines}
            cards[keys[0]] = {**ordered, "updated": now, **({"by": signed} if signed else {})}
        return Specs(cards)

    def write(self, path) -> None:
        """Written through a temporary file: an interrupted write leaves no half-file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".specs-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump({"devices": self.cards}, file, ensure_ascii=False, indent=1)
                file.write("\n")
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def listed(self, devices, atlas, tongue: Tongue) -> list:
        """Every device on the map with its card, cards first; then the cards whose device the
        snapshot does not hold. A card is never dropped from the list for being offline."""
        entries, used = [], set()
        for device in devices:
            addresses = [seat.ip for seat in device.seats]
            kept_under, card = self.found(device.key, *addresses)
            used.add(kept_under)
            entries.append(self.entry(device.key, device.name, device.kind, addresses, device.online,
                                      True, card, tongue))
        for key, card in self.cards.items():
            if key not in used:
                known = atlas.device(key)
                entries.append(self.entry(key, known.get("name", ""), known.get("kind", ""), [], False,
                                          False, card, tongue))
        return sorted(entries, key=lambda one: (one["specs"] is None, one["name"].casefold() or "￿", one["device"]))

    def entry(self, key, name, kind, addresses, online, present, card, tongue) -> dict:
        lines = {name_: value for name_, value in card.items() if name_ not in self.STAMPS}
        return {"device": key, "name": name, "kind": kind, "addresses": addresses, "online": online,
                "present": present, "specs": lines or None, "updated": card.get("updated", ""),
                "by": card.get("by", ""), "lines": CardText(card, tongue).lines()}


@dataclass(frozen=True)
class CardText:
    """A card in words, in one language: the same lines on the map's scroll, on the page of
    cards and in /specs.md, worked out here once."""

    card: dict
    tongue: Tongue

    def say(self, key: str, **parts) -> str:
        return self.tongue.say(key, **parts)

    def gb(self, size) -> str:
        """Gigabytes as a reader counts them: from a thousand on, terabytes."""
        if size >= 1000:
            tb = size / 1000
            return self.say("specs.tb", tb=int(tb) if float(tb).is_integer() else round(tb, 2))
        return self.say("specs.gb", gb=size)

    def lines(self) -> list:
        """What the card holds, line by line; nothing for an empty card."""
        card, said = self.card, []
        if card.get("model"):
            said.append(self.say("specs.line.model", model=card["model"]))
        system = " ".join(part for part in (card.get("os"), card.get("os_version")) if part)
        system = ", ".join(part for part in (system, card.get("arch")) if part)
        if system:
            said.append(self.say("specs.line.system", system=system))
        if card.get("cpu"):
            said.append(self.say("specs.line.cpu", cpu=card["cpu"]))
        if card.get("cores"):
            said.append(self.say("specs.line.cores", cores=card["cores"]))
        if card.get("threads"):
            said.append(self.say("specs.line.threads", threads=card["threads"]))
        ram = ", ".join(part for part in (self.gb(card["ram_gb"]) if card.get("ram_gb") else "",
                                          card.get("ram_type", "")) if part)
        if ram:
            said.append(self.say("specs.line.ram", ram=ram))
        if card.get("disks"):
            disks = "; ".join(" ".join(part for part in (self.gb(disk["size_gb"]), disk.get("type", "")) if part)
                              for disk in card["disks"])
            said.append(self.say("specs.line.disks", disks=disks))
        for key in ("gpu", "role", "notes"):
            if card.get(key):
                said.append(self.say(f"specs.line.{key}", **{key: card[key]}))
        if said and card.get("updated"):
            time = f"{card['updated'][:16].replace('T', ' ')} UTC"
            said.append(self.say("specs.line.by", by=card["by"], time=time) if card.get("by")
                        else self.say("specs.line.when", time=time))
        return said


@dataclass(frozen=True)
class SpecsText:
    """The cards in words, for an agent: what each of the owner's machines is made of, what is
    not written down yet, and how to write it."""

    entries: list
    tongue: Tongue
    missing: str = ""

    def say(self, key: str, **parts) -> str:
        return self.tongue.say(key, **parts)

    def markdown(self) -> str:
        cards = [one for one in self.entries if one["specs"]]
        bare = [one for one in self.entries if not one["specs"]]
        lines = ["# " + self.say("specs.title"), "", self.say("specs.about"), ""]
        if self.missing:
            lines += [self.missing, ""]
        if not cards:
            lines += [self.say("specs.none"), ""]
        for one in cards:
            where = ", ".join(one["addresses"]) or self.say("specs.absent")
            lines += [f"## {one['name'] or self.say('specs.nameless')} — {where}", "",
                      "- " + self.say("specs.key", device=one["device"]),
                      *("- " + line for line in one["lines"]), ""]
        if bare:
            listed = ", ".join(f"{one['name'] or self.say('specs.nameless')} ({', '.join(one['addresses']) or '—'})"
                               for one in bare)
            lines += ["## " + self.say("specs.bare"), "", self.say("specs.bare.count", count=len(bare)) + " " + listed, ""]
        lines += ["## " + self.say("specs.how"), "", self.say("specs.how.about"), "",
                  "- `device` — " + self.say("specs.how.device"),
                  "- `name` — " + self.say("specs.how.name"),
                  *(f"- `{key}` — " + self.say(f"specs.field.{key}") for key in Specs.keys()),
                  "- `by` — " + self.say("specs.how.by"), "",
                  self.say("specs.how.wipe"), "", self.say("specs.how.example"), ""]
        return "\n".join(lines).rstrip() + "\n"

"""The same map, but in words: for whoever reads rather than looks.

The picture is drawn by a browser, and an agent has no business in it: clicking is not
something it does, and retelling a drawing means making things up. So the same facts are given
as text, in tables that read the same way to a human and to a program.

Nothing is worked out again here. This is exactly the lump that goes to the page, only said in
words — otherwise the text and the picture would one day disagree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .tongue import Tongue, known

#: How the router writes a span: "21w5d3h54m45s". Two leading parts are enough for a human.
SPANS = ("w", "d", "h", "m", "s")


def ago(last: str, tongue: Tongue) -> str:
    """"21w5d3h54m45s" becomes "seen 21w 5d ago". "never" means not at this address."""
    if not last:
        return ""
    if last == "never":
        return tongue.say("ago.never")
    parts = [tongue.say(f"span.unit.{unit}", number=number)
             for number, unit in re.findall(r"(\d+)([wdhms])", last) if unit in SPANS]
    return tongue.say("ago.seen", span=" ".join(parts[:2])) if parts else ""


def cell(text) -> str:
    """A table cell. A bar inside a value would tear the table apart, so it is escaped."""
    return str(text if text not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")


@dataclass(frozen=True)
class Scribe:
    """One telling of the network: holds the lump and lays it out in sections."""

    payload: dict
    tongue: Tongue

    @classmethod
    def of(cls, payload: dict, tongue: Tongue | None = None) -> "Scribe":
        return cls(payload, tongue or Tongue.of())

    def say(self, key: str, **parts) -> str:
        return self.tongue.say(key, **parts)

    # --- odds and ends --------------------------------------------------------------------------
    @property
    def titles(self) -> dict:
        ends = self.payload.get("ends", {})
        known = {segment["key"]: segment["title"] for segment in self.payload["segments"]}
        known.setdefault(ends.get("internet", "internet"), self.say("end.internet"))
        known.setdefault(ends.get("router", "router"), self.say("end.router"))
        return known

    def title(self, key: str) -> str:
        return self.titles.get(key, key)

    @staticmethod
    def table(head: list, rows: list) -> list:
        if not rows:
            return []
        lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
        lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
        return lines + [""]

    def seat_of(self, device: dict) -> dict:
        return next((seat for seat in device["seats"] if seat["online"]),
                    device["seats"][0] if device["seats"] else {})

    def living(self, key: str) -> list:
        """This network's devices. Home is where a device is now; failing that, where it is remembered."""
        found = [device for device in self.payload["devices"]
                 if key in (device["homes"] or [seat["segment"] for seat in device["seats"]])]
        return sorted(found, key=lambda device: (not device["online"], device["name"].lower()))

    # --- sections -------------------------------------------------------------------------------
    def head(self) -> list:
        return [
            "# " + self.say("md.title"),
            "",
            self.say("md.taken", taken=self.payload.get("taken") or self.say("md.taken-unknown")),
            "",
            self.say("md.intro"),
            "",
        ]

    def networks(self) -> list:
        # A name may be the map's own, or it may be the interface's name on the router. The
        # second column earns its place only in the first case: two equal columns explain nothing.
        # The yard beyond the gate has a section of its own, below: its rules are not ours.
        ours = [segment for segment in self.payload["segments"] if not segment.get("outside")]
        renamed = any(segment["title"] != segment["key"] for segment in ours)
        rows = []
        for segment in ours:
            here = [device for device in self.living(segment["key"]) if device["online"]]
            row = [segment["title"]] + ([segment["key"]] if renamed else [])
            rows.append(row + [segment["network"],
                               segment["vlan"] or self.say("md.vlan.none"),
                               segment["gateway"],
                               self.say("md.online.count", here=len(here),
                                        all=len(self.living(segment["key"]))),
                               self.say("md.lives.temporary" if segment["temporary"]
                                        else "md.lives.always")])
        head = [self.say("md.col.title")] + ([self.say("md.col.interface")] if renamed else []) + [
            self.say("md.col.addresses"), self.say("md.col.vlan"), self.say("md.col.gateway"),
            self.say("md.col.online"), self.say("md.col.lives")]
        about = [self.say("md.networks.renamed" if renamed else "md.networks.same"), ""]
        return ["## " + self.say("md.networks.head"), "", *about, *self.table(head, rows)]

    def access(self) -> list:
        rows = []
        for road in self.payload["roads"]:
            if road["width"] == "shut":
                continue
            allowed = self.say(f"md.width.{road['width']}")
            if road["signs"]:
                allowed += ": " + "; ".join(road["signs"])
            if road["shutTo"]:
                allowed += self.say("md.access.except", where=road["shutTo"])
            rules = "; ".join(dict.fromkeys(
                self.say("md.access.rule", index=rule["index"], comment=rule["comment"])
                for opening in road["openings"] for rule in opening["rules"])) \
                or self.say("md.access.no-rule")
            rows.append([self.title(road["source"]), self.title(road["target"]), allowed,
                         self.say("md.access.only", name=road["only"]) if road["only"]
                         else self.say("md.access.anyone"), rules])
        return ["## " + self.say("md.access.head"), "", self.say("md.access.intro"), "",
                *self.table([self.say("md.col.from"), self.say("md.col.to"),
                             self.say("md.col.allowed"), self.say("md.col.who"),
                             self.say("md.col.opened-by")], rows)]

    def gate(self) -> list:
        """DSM's own gate on the NAS. The table above is the router's answer, and for a name the
        NAS serves it is not the last word: DSM may turn a network away, or lead it on further."""
        gate = self.payload.get("gate")
        if gate is None:
            return []
        lines = ["## " + self.say("md.gate.head"), "", self.say("gate.intro"), ""]
        if gate["missing"]:
            return lines + [self.say(gate["missing"]), ""]
        rows = [[door["name"], self.leads(door), self.profile(door), self.who(door["refuses"]), self.who(door["past"])]
                for door in gate["doors"]]
        unclear = [self.say("md.gate.unclear", name=door["name"], who=", ".join(self.title(key) for key in door["unclear"]))
                   for door in gate["doors"] if door["unclear"]]
        return (lines + self.table([self.say(f"md.gate.col.{key}") for key in ("name", "to", "profile", "refuses", "past")],
                                   rows)
                + [f"- {line}" for line in unclear] + ([""] if unclear else [])
                + [gate["wall"], "", self.say("gate.taken", time=gate["taken"] or "?")
                   + (" " + self.say("gate.stale") if gate["stale"] else ""), ""])

    def leads(self, door: dict) -> str:
        """Where a name leads: the NAS itself, or another machine and the network it stands in."""
        if door["local"]:
            return self.say("md.gate.local", to=door["to"])
        return door["to"] + (f" ({self.title(door['beyond'])})" if door["beyond"] else "")

    def profile(self, door: dict) -> str:
        if door["profile"] is None:
            return self.say("md.gate.no-profile")
        if door["profile"] == "unread":
            return self.say("gate.profile.unread")
        return ", ".join(f"{action} {source}" for action, source in door["profile"])

    def who(self, parts: list) -> str:
        """Networks by title; the addresses as well when only a part of a network is meant."""
        return ", ".join(self.title(part["segment"]) + ("" if part["whole"] else f" ({part['space']})")
                         for part in parts)

    def devices(self) -> list:
        lines = ["## " + self.say("md.devices.head"), "", self.say("md.devices.intro"), ""]
        for segment in self.payload["segments"]:
            if segment.get("outside"):
                continue     # told in the outpost's own section, with what the router saw there
            found = self.living(segment["key"])
            if not found:
                continue
            rows = []
            for device in found:
                seat = self.seat_of(device)
                state = (self.say("md.state.online") if device["online"]
                         else ago(seat.get("last", ""), self.tongue) or self.say("md.state.offline"))
                rows.append([device["name"] or self.say("md.device.nameless"), seat.get("ip", ""),
                             self.kind(device["kind"]), state,
                             self.say("md.yes") if device["twin"] else ""])
            lines += [f"### {segment['title']} · {segment['network']}", "",
                      *self.table([self.say("md.col.name"), self.say("md.col.address"),
                                   self.say("md.col.kind"), self.say("md.col.state"),
                                   self.say("md.col.twin")], rows)]
        return lines

    def kind(self, code: str) -> str:
        return self.say(f"kind.{code}") if code else self.say("md.kind.unknown")

    def outpost(self) -> list:
        """The network beyond the gate. It is kept out of the networks: those rules are not ours."""
        post = self.payload.get("outpost")
        if not post:
            return []
        lines = ["## " + self.say("md.outpost.head"), "",
                 self.say("md.outpost.about", network=post["network"],
                          interface=post["interface"], ours=post["ours"])
                 + (self.say("md.outpost.gate", gate=post["gate"]) if post["gate"]
                    else self.say("md.outpost.no-gate")),
                 "",
                 self.say("md.outpost.not-ours"), ""]
        rows = [[one["ip"], one["mac"]] for one in post["neighbours"]]
        return lines + (self.table([self.say("md.col.address"), self.say("md.col.mac")], rows)
                        if rows else [self.say("md.outpost.none-seen"), ""])

    def doubts(self) -> list:
        """What the map did not understand. Without this the text would look fuller than it is."""
        notes = list(self.payload.get("notes", []))
        findings = [self.say("md.doubts.finding", kind=self.say(f"find.kind.{finding['kind']}"),
                             text=finding["text"])
                    for finding in self.payload.get("findings", [])]
        head = ["## " + self.say("md.doubts.head"), ""]
        if not notes and not findings:
            return head + [self.say("md.doubts.none"), ""]
        return head + [self.say("md.doubts.intro"), "",
                       *[f"- {line}" for line in findings + notes], ""]

    def machine(self) -> list:
        return ["## " + self.say("md.machine.head"), "",
                "- " + self.say("md.machine.map"),
                "- " + self.say("md.machine.history"),
                "- " + self.say("md.machine.story"),
                "- " + self.say("md.machine.refresh"),
                "- " + self.say("md.machine.specs"),
                "",
                self.say("md.machine.readonly"), ""]

    def markdown(self) -> str:
        lines = [*self.head(), *self.networks(), *self.access(), *self.gate(), *self.devices(),
                 *self.outpost(), *self.doubts(), *self.machine()]
        return "\n".join(lines).rstrip() + "\n"


def guide(tongue: Tongue | None = None) -> str:
    """A signpost for whoever arrives and would rather not work out the buttons.

    It lives at /llms.txt, where reading agents look first. The point of the file is that the
    page need not be walked click by click: everything worth having is named at once."""
    tongue = tongue or Tongue.of()
    say = tongue.say
    langs = ", ".join(f"`?lang={one['code']}` — {one['name']}" for one in known())
    return "\n".join([
        "# " + say("llms.title"),
        "",
        "> " + say("llms.about"),
        "",
        say("llms.no-clicking"),
        "",
        "## " + say("llms.start.head"),
        "",
        "- " + say("llms.start.fresh"),
        "- " + say("llms.start.story"),
        "- " + say("llms.start.containers"),
        "- " + say("llms.start.specs"),
        "",
        "## " + say("llms.machine.head"),
        "",
        "- " + say("llms.machine.map"),
        "- " + say("llms.machine.history"),
        "- " + say("llms.machine.houses"),
        "- " + say("llms.machine.names"),
        "- " + say("llms.machine.containers"),
        "- " + say("llms.machine.specs"),
        "- " + say("llms.machine.openapi"),
        "- " + say("llms.machine.packages"),
        "",
        "## " + say("llms.lang.head"),
        "",
        say("llms.lang.about", langs=langs),
        "",
        "## " + say("llms.mind.head"),
        "",
        "- " + say("llms.mind.snapshot"),
        "- " + say("llms.mind.default-deny"),
        "- " + say("llms.mind.gate"),
        "- " + say("llms.mind.doubts"),
        "",
    ])

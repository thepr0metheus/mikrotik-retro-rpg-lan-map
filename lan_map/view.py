"""What the page sees: castles, houses, roads and the journal, in one lump of JSON.

Nothing is decided here afresh. The facts have been worked out by the model and the reader of
rules; here they are laid out so that the page has only to draw. That is why the picture can
be checked without a browser: this lump is checked whole by a test.

This is also where codes become words. Everything inside the map travels as a code, and only
here does it turn into a phrase in the language that was asked for. Three codes stay codes on
purpose — a road's width, a finding's kind and a device's kind — because the page draws
differently for each, and it says them in words out of the very same dictionary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from .atlas import Atlas
from .changes import Changes
from .destinations import Destinations
from .model import Network
from .memory import Memory
from .overseas import Overseas
from .ports import behind
from .roads import INTERNET, ROUTER, Roads
from .spans import ANY_PORT, NOBODY, NO_PORTS
from .tongue import Said, Tongue
from .traffic import Traffic
from .sprites import Sprites

#: Words for the handful of things that are not addresses or numbers.
PLAIN = {NOBODY: "space.nobody", NO_PORTS: "space.no-ports", ANY_PORT: "space.any-port",
         "any": "space.any"}


@dataclass(frozen=True)
class View:
    """One picture of the world for the page."""

    #: Castle colours in order. The atlas may name its own.
    COLOURS: ClassVar[tuple] = ("#1d9e75", "#7f77dd", "#f0a020", "#3f6fb5", "#d4537e", "#639922")
    #: How many far ends the signpost by the pier names: one plank each.
    SIGNPOST: ClassVar[int] = 3

    network: Network
    roads: Roads
    atlas: Atlas
    sprites: Sprites
    snapshot: object = None
    #: The previous snapshot, when there is one: "what changed" is worked out against it.
    before: object = None
    #: The language every phrase in this picture is said in.
    tongue: Tongue = None
    #: Who is out there beyond the sea: the written houses plus whatever the reader added.
    overseas: Overseas = None
    #: The names the router gave before and his cache has since let go of.
    memory: Memory = None
    #: Worked out once per picture: rule captions do not change until the snapshot does.
    _comments: dict = field(default=None, compare=False)

    @classmethod
    def of(cls, snapshot, atlas: Atlas, sprites: Sprites | None = None, before=None,
           tongue: Tongue | None = None, overseas: Overseas | None = None,
           memory: Memory | None = None) -> "View":
        network = Network.of(snapshot, atlas)
        return cls(network, Roads.of(snapshot, network), atlas, sprites or Sprites.read(),
                   snapshot, before, tongue or Tongue.of(), overseas or Overseas(),
                   memory=memory or Memory())

    def word(self, text: str) -> str:
        """A code that stands for a word becomes one; an address or a port stays itself."""
        return self.tongue.say(PLAIN[text]) if text in PLAIN else text

    def payload(self) -> dict:
        traffic = self.who_walks()
        return {
            "lang": self.tongue.code,
            "taken": self.network.taken,
            "segments": [self.segment(segment, order) for order, segment in enumerate(self.network.segments)],
            "devices": [self.device(device) for device in self.network.devices],
            "roads": [self.road(road) for road in self.roads.roads],
            "findings": [self.finding(finding) for finding in self.roads.findings],
            "notes": [self.tongue.tell(note) for note in
                      list(self.roads.notes) + list(self.network.puzzles) + self.about_kinds()],
            "ends": {"internet": INTERNET, "router": ROUTER},
            "outpost": self.outpost(),
            "changes": self.what_changed(),
            "traffic": traffic,
            # The busiest far ends out in the world, by the same reckoning as the page of
            # services: the signpost by the pier names them, and leads to that page.
            "signpost": [one["who"] for one in
                         Destinations.of(traffic["trips"]).payload()["known"][:self.SIGNPOST]],
        }

    def outpost(self):
        """The network beyond the gate. It is kept out of the castles on purpose: not ours."""
        post = self.network.outpost
        if not post:
            return None
        return {"interface": post.interface, "network": post.network, "ours": post.ours,
                "gate": post.gate,
                "neighbours": [{"ip": ip, "mac": mac} for ip, mac in post.neighbours]}

    def who_walks(self) -> dict:
        traffic = Traffic.of(self.snapshot, self.network, self.memory)
        ours = {seat.ip for device in self.network.devices for seat in device.seats}
        walks = {ip: [{**trip, "about": self.tongue.say(behind(trip["port"], trip["protocol"])),
                       **(self.overseas or Overseas()).whose(trip["name"], trip["to"],
                                                             trip["remembered"])}
                      for trip in traffic.walks(ip)]
                 for ip in sorted(ours) if traffic.trips.get(ip)}
        return {"rows": traffic.rows(), "missing": self.tongue.tell(traffic.missing),
                "trips": walks}

    def what_changed(self) -> dict:
        changes = Changes.between(self.before, self.snapshot, self.atlas)
        return {"before": changes.before,
                "lines": [self.tongue.tell(line) for line in changes.lines]}

    def segment(self, segment, order: int) -> dict:
        named = self.atlas.segments.get(segment.key, {})
        return {"key": segment.key, "title": segment.title, "network": segment.network,
                "gateway": segment.gateway, "vlan": segment.vlan, "trusted": segment.trusted,
                "temporary": segment.temporary,
                "colour": named.get("colour", self.COLOURS[order % len(self.COLOURS)])}

    def device(self, device) -> dict:
        known = self.atlas.device(device.key, *(seat.ip for seat in device.seats))
        return {"key": device.key, "name": device.name, "kind": device.kind,
                "hidden": bool(known.get("hidden")), "pinned": bool(known.get("pinned")),
                "known": self.sprites.has(device.kind) if device.kind else True,
                "online": device.online, "homes": list(device.homes),
                "twin": device.in_two_castles,
                "seats": [{"ip": seat.ip, "segment": seat.segment, "online": seat.online,
                           "seen": list(seat.seen), "last": seat.last} for seat in device.seats]}

    def road(self, road) -> dict:
        return {"source": road.source, "target": road.target, "width": road.width,
                "signs": [self.tongue.tell(sign) for sign in road.signs],
                "byDefault": road.by_default, "dead": road.dead,
                "shutTo": self.word(road.shut_to),
                "renamed": [self.rule(rule) for rule in road.renamed],
                "shutBy": [self.rule(rule) for rule in road.shut_by],
                "shutParts": [{"where": piece.where, "by": [self.rule(rule) for rule in piece.rules]}
                              for piece in road.shut],
                "puzzles": [self.rule(rule) for rule in road.puzzles],
                "only": self.only(road),
                "openings": [{"source": self.word(opening.source),
                              "target": self.word(opening.target),
                              "protocol": self.word(opening.protocol),
                              "ports": self.word(opening.ports),
                              "byDefault": opening.by_default,
                              "from": [list(span) for span in opening.source_spans],
                              "to": [list(span) for span in opening.target_spans],
                              "rules": [self.rule(rule) for rule in opening.rules]}
                             for opening in road.openings]}

    def only(self, road) -> str:
        """"Only the NAS": when the whole road leads to one house, that house is named."""
        targets = {opening.target for opening in road.openings}
        if len(targets) != 1:
            return ""
        target = targets.pop()
        if "/" in target or "-" in target:
            return ""
        for device in self.network.devices:
            if any(seat.ip == target for seat in device.seats):
                return device.name or target
        return target

    def finding(self, finding) -> dict:
        return {"kind": finding.kind, "text": self.tongue.tell(finding.said),
                "rules": [self.rule(rule) for rule in finding.rules]}

    def rule(self, rule) -> dict:
        return {"index": rule.index, "action": rule.action, "comment": rule.comment,
                "packets": rule.packets, "id": rule.id, "command": self.command(rule)}

    def command(self, rule) -> str:
        """A line ready for the router. A human runs it: the map never changes the network."""
        if not rule.id:
            return ""
        if rule.comment and self.comments().get(rule.comment, 0) == 1:
            return f'/ip firewall filter remove [find comment="{rule.comment}"]'
        return f"/ip firewall filter remove {rule.id}"

    def comments(self) -> dict:
        """How many rules share one caption: when it is the only one, searching by it is safe."""
        if self._comments is None:
            seen: dict = {}
            for row in (self.snapshot.tables.get("ip/firewall/filter", []) if self.snapshot else []):
                comment = row.get("comment", "")
                if comment:
                    seen[comment] = seen.get(comment, 0) + 1
            object.__setattr__(self, "_comments", seen)
        return self._comments

    def about_kinds(self) -> list:
        """A kind with no picture: we draw a house and say so out loud."""
        unknown = self.sprites.unknown(device.kind for device in self.network.devices)
        return [Said.of("note.unknown-kind", kind=kind) for kind in unknown]

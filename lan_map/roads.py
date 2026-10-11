"""Roads: who may start a connection, to where, and on which ports.

A road is worked out from the firewall rules in their own order: the first rule that matches
decides. The map asks "who may call", not "which packets get through": established and related
are the answer inside a conversation already begun, and they do not change a road's width.

The space of addresses and ports is cut into pieces along the rules' own boundaries. Every
rule sees each piece whole, so the answer for a piece is single and can be named exactly:
"the whole network", or "only 192.168.40.107-192.168.40.108".

What a rule never explained is called unread and is shown as such. A guess would look like a
fact on the map without being one.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar
from itertools import product

from .model import Network
from .spans import ANY_PORT, Space, Unclear
from .tongue import Said

#: What a rule does to a connection. Codes, not words: the language comes later.
PASS = "pass"
STOP = "stop"
PUZZLE = "puzzle"

#: Actions that decide the fate of a connection.
DECIDING = {"accept": PASS, "drop": STOP, "reject": STOP}
#: Address-translating actions: they do not decide whether to let through, but they change
#: the name of whoever is walking.
NAT = {"masquerade", "src-nat", "dst-nat", "netmap", "redirect", "same"}
#: Actions that decide nothing: the rule counts or marks packets and hands over to the next.
PASSING = {"passthrough", "log", "fasttrack-connection", "sniff-tzsp",
           "add-src-to-address-list", "add-dst-to-address-list"}
#: Fields that change nothing: these are bookkeeping, not conditions.
PLAIN = {".id", "action", "chain", "comment", "bytes", "packets", "dynamic", "invalid", "disabled",
         "log", "log-prefix", "place-before"}
#: Conditions we do read.
UNDERSTOOD = {"src-address", "dst-address", "src-address-list", "dst-address-list",
              "in-interface", "out-interface", "in-interface-list", "out-interface-list",
              "protocol", "dst-port", "src-port", "port", "connection-state"}
#: Conditions that have nothing to do with two castles talking. The reason is said out loud.
ASIDE = {"ipsec-policy": Said.of("aside.ipsec")}


@dataclass(frozen=True)
class Faces:
    """The interfaces a rule looks through: "these", or "any but these"."""
    names: frozenset
    inside: bool = True

    def matches(self, given: frozenset) -> bool:
        return bool(self.names & given) if self.inside else not (self.names & given)


@dataclass(frozen=True)
class RuleRef:
    """A rule as the scroll shows it: what opened the road and how often it fired."""
    index: int
    action: str
    comment: str
    packets: int
    #: The router's own id for the rule (*1A). It is how a human finds and removes it.
    id: str = ""

    @property
    def dead(self) -> bool:
        return self.packets == 0


@dataclass(frozen=True)
class Rule:
    index: int
    chain: str
    action: str
    ref: RuleRef
    disabled: bool
    source: Space
    target: Space
    protocol: str
    ports: Space
    #: The interfaces the rule looks through. None means any.
    comes_in: frozenset | None = None
    goes_out: frozenset | None = None
    #: Whether the rule decides the fate of a new connection.
    starts_new: bool = True
    #: Why the rule was set aside. Not empty means it takes no part in two castles talking.
    aside: tuple = ()
    #: What we did not understand in the rule. Not empty makes the answer "unread".
    unknown: tuple = ()

    @property
    def decides(self) -> bool:
        return self.action in DECIDING or bool(self.unknown)

    def may_touch(self, journey: "Journey") -> bool:
        """Whether the rule has a say about this road."""
        if self.aside or not self.starts_new or not self.decides:
            return False
        return self.touches(journey)

    def touches(self, journey: "Journey") -> bool:
        """Whether the rule lands on this road by addresses and interfaces."""
        if self.disabled:
            return False
        if not (self.source.overlaps(journey.source) and self.target.overlaps(journey.target)):
            return False
        return self._interface(self.comes_in, journey.comes_in) and self._interface(self.goes_out, journey.goes_out)

    @staticmethod
    def _interface(wanted, given) -> bool:
        return wanted is None or wanted.matches(given)

    def covers(self, cell: "Cell") -> bool:
        """Whether the rule fits the piece. Pieces are cut so that "partly" cannot happen."""
        if self.protocol and self.protocol != cell.protocol:
            return False
        return (self.source.overlaps(cell.source) and self.target.overlaps(cell.target)
                and self.ports.overlaps(cell.ports))


@dataclass(frozen=True)
class Journey:
    """One question: from which addresses to which, and through which interfaces."""
    source: Space
    target: Space
    comes_in: frozenset
    goes_out: frozenset


@dataclass(frozen=True)
class Cell:
    """A piece of the space: addresses, protocol, ports. Its answer is always single."""
    source: Space
    target: Space
    protocol: str
    ports: Space


@dataclass(frozen=True)
class Opening:
    """What travels the road: from where, to where, by which protocol and on which ports."""
    source: str
    target: str
    protocol: str
    ports: str
    by_default: bool
    rules: tuple
    #: The same addresses as numbers: this is how the map decides whether one device sees
    #: this road at all.
    source_spans: tuple = ()
    target_spans: tuple = ()

    @property
    def dead(self) -> bool:
        """Opened by a rule that never fired once: such a road grows over with moss."""
        return bool(self.rules) and all(rule.dead for rule in self.rules)


@dataclass(frozen=True)
class Shut:
    """One piece of where a road does not reach, and the rules that shut it there."""
    where: str
    rules: tuple = ()


@dataclass(frozen=True)
class Road:
    source: str
    target: str
    width: str
    openings: tuple = ()
    #: Open not by a rule but by the absence of one: RouterOS forward lets through by default.
    by_default: bool = False
    #: Rules we could not read.
    puzzles: tuple = ()
    #: srcnat rules: whoever is called will see the router, not the guest.
    renamed: tuple = ()
    #: Where this road does not reach, when addresses are the only reason: piece by piece.
    shut: tuple = ()
    #: The rules that shut this road. Empty means there was nothing to shut: nobody opened it.
    shut_by: tuple = ()

    @property
    def shut_to(self) -> str:
        """Where this road does not reach, in one line."""
        return ", ".join(piece.where for piece in self.shut)

    @property
    def dead(self) -> bool:
        """Everything that opens the road never fired: on the map it grows over with moss."""
        return bool(self.openings) and all(opening.dead for opening in self.openings)

    @property
    def signs(self) -> tuple:
        """The short sign by the road: protocols and ports, without repeats.

        When everything is open the sign is pointless: the width of the road already says so."""
        if self.width in (ALL, SHUT, PUZZLE):
            return ()
        seen = []
        for opening in self.openings:
            sign = (Said.of("sign.protocol", protocol=Said.of(f"space.{opening.protocol}")
                            if opening.protocol == "any" else opening.protocol)
                    if opening.ports == ANY_PORT
                    else Said.of("sign.protocol-ports",
                                 protocol=Said.of(f"space.{opening.protocol}")
                                 if opening.protocol == "any" else opening.protocol,
                                 ports=opening.ports))
            if sign not in seen:
                seen.append(sign)
        return tuple(seen)


#: How wide a road is. Codes: the words for them live in the dictionary.
ALL, MOST, PORTS, SHUT = "all", "most", "ports", "shut"


class Chain:
    """One chain's rules in their order. The first match decides — as in the router itself."""

    def __init__(self, rules, policy: str = PASS):
        self.rules = tuple(rules)
        self.policy = policy

    def road(self, source: str, target: str, journey: Journey) -> Road:
        rules = [rule for rule in self.rules if rule.may_touch(journey)]
        answers = [(cell, *self.decide(cell, rules)) for cell in self.cells(journey, rules)]
        puzzles = tuple(dict.fromkeys(rule.ref for cell, verdict, rule in answers
                                      if verdict == PUZZLE and rule is not None))
        openings = self.openings([(cell, rule) for cell, verdict, rule in answers if verdict == PASS])
        width, shut = self.width(answers, puzzles)
        closed = tuple(dict.fromkeys(rule.ref for cell, verdict, rule in answers
                                     if verdict == STOP and rule is not None))
        return Road(source, target, width, openings,
                    by_default=any(opening.by_default for opening in openings),
                    puzzles=puzzles, shut=self.pieces(shut, answers), shut_by=closed)

    @staticmethod
    def width(answers, puzzles) -> tuple:
        """How wide the road is and, when addresses are the only reason, where it stops."""
        if puzzles:
            return PUZZLE, Space()
        by_target: dict = {}
        for cell, verdict, _ in answers:
            by_target.setdefault(cell.target.spans, set()).add(verdict)
        open_targets = [spans for spans, verdicts in by_target.items() if verdicts == {PASS}]
        shut_targets = [spans for spans, verdicts in by_target.items() if verdicts == {STOP}]
        mixed = len(by_target) - len(open_targets) - len(shut_targets)
        if not open_targets and not mixed:
            return SHUT, Space()
        if not shut_targets and not mixed:
            return ALL, Space()
        if mixed:
            return PORTS, Space()
        shut = Space()
        for spans in shut_targets:
            shut = shut | Space(spans)
        return MOST, shut

    @staticmethod
    def pieces(shut: Space, answers) -> tuple:
        """Where the road stops, piece by piece, each with the rules that stop it there: two
        rules shut two different networks, and each network is told its own."""
        found = []
        for span in shut.spans:
            piece = Space((span,))
            rules = tuple(dict.fromkeys(rule.ref for cell, verdict, rule in answers
                                        if verdict == STOP and rule is not None
                                        and cell.target.overlaps(piece)))
            found.append(Shut(piece.address_text(), rules))
        return tuple(found)

    def cells(self, journey: Journey, rules) -> list:
        """Cutting the space along the rules' bounds: finer is pointless, coarser would lie."""
        sources = journey.source.split(self.bounds(rules, "source"))
        targets = journey.target.split(self.bounds(rules, "target"))
        protocols = [""] + sorted({rule.protocol for rule in rules if rule.protocol})
        found = []
        for protocol in protocols:
            fitting = [rule for rule in rules if not rule.protocol or rule.protocol == protocol]
            ports = Space.ports("").split(self.bounds(fitting, "ports"))
            found += [Cell(*pair, protocol, port) for pair, port in product(product(sources, targets), ports)]
        return found

    @staticmethod
    def bounds(rules, what: str) -> set:
        marks = set()
        for rule in rules:
            marks |= getattr(rule, what).bounds()
        return marks

    def decide(self, cell: Cell, rules) -> tuple:
        for rule in rules:
            if not rule.covers(cell):
                continue
            if rule.unknown:
                return PUZZLE, rule
            return DECIDING[rule.action], rule
        return self.policy, None

    @staticmethod
    def openings(passed) -> tuple:
        """The pieces that pass are folded back into lines a human can read."""
        by_ports: dict = {}
        for cell, rule in passed:
            key = (cell.source.spans, cell.target.spans, cell.protocol, rule.ref if rule else None)
            by_ports[key] = by_ports.get(key, Space()) | cell.ports
        by_source: dict = {}
        for (source, target, protocol, ref), ports in by_ports.items():
            key = (target, protocol, ports.spans, ref)
            by_source[key] = by_source.get(key, Space()) | Space(source)
        found = []
        for (target, protocol, ports, ref), source in by_source.items():
            found.append(Opening(source=source.address_text(), target=Space(target).address_text(),
                                 protocol=protocol or "any", ports=Space(ports).ports_text(),
                                 by_default=ref is None, rules=() if ref is None else (ref,),
                                 source_spans=source.spans, target_spans=tuple(target)))
        return tuple(sorted(found, key=lambda opening: (opening.target, opening.protocol, opening.ports)))


class Reader:
    """Reads the router's rules. What it failed to understand it records, never discards."""

    def __init__(self, lists: dict, members: dict, lists_known: bool = True):
        self.lists = lists          # address-list name → Space
        self.members = members      # interface-list name → set of interfaces
        #: The snapshot does have the address-list table. Then a name missing from it is an
        #: empty list, and an empty list in RouterOS matches nobody.
        self.lists_known = lists_known

    def rules(self, rows, chain: str) -> list:
        return [self.rule(index, row) for index, row in enumerate(rows) if row.get("chain") == chain]

    def rule(self, index: int, row: dict) -> Rule:
        unknown = [Said.of("rule.unknown-condition", name=key) for key in row
                   if key not in PLAIN and key not in UNDERSTOOD and key not in ASIDE]
        action = row.get("action", "")
        if action not in DECIDING and action not in PASSING and action not in NAT:
            unknown.append(Said.of("rule.unknown-action", name=action))
        source, source_trouble = self.space(row, "src-address", "src-address-list")
        target, target_trouble = self.space(row, "dst-address", "dst-address-list")
        ports, ports_trouble = self.ports(row)
        comes_in, in_trouble = self.interfaces(row, "in-interface", "in-interface-list")
        goes_out, out_trouble = self.interfaces(row, "out-interface", "out-interface-list")
        unknown += [note for note in (source_trouble, target_trouble, ports_trouble,
                                      in_trouble, out_trouble) if note]
        states = {state.strip() for state in row.get("connection-state", "").split(",") if state.strip()}
        aside = tuple(ASIDE[key] for key in row if key in ASIDE)
        return Rule(
            index=index, chain=row.get("chain", ""), action=action,
            ref=RuleRef(index, action, row.get("comment", ""), int(row.get("packets", 0) or 0),
                        row.get(".id", "")),
            disabled=row.get("disabled") == "true",
            source=source, target=target, protocol=row.get("protocol", ""), ports=ports,
            comes_in=comes_in, goes_out=goes_out,
            starts_new=not states or "new" in states, aside=aside, unknown=tuple(unknown))

    @staticmethod
    def apart(value: str) -> tuple:
        """
        `!name` the router reads as "anything but that": the mark is grammar, not part of the name.

        For plain addresses `Space.addresses` reads the same mark itself, and this must not
        read it a second time — a name and an address are two grammars, one owner each.
        """
        return value.lstrip("!"), value.startswith("!")

    @staticmethod
    def but(space: Space, other_way: bool) -> Space:
        return Space.whole() - space if other_way else space

    def space(self, row: dict, plain: str, listed: str) -> tuple:
        """The condition's addresses. An unreadable condition widens the rule: silence is worse."""
        spaces, trouble = [], None
        if plain in row:
            try:
                spaces.append(Space.addresses(row[plain]))
            except Unclear as error:
                trouble = Said.of("rule.bad-condition", name=plain, why=error.said)
        if listed in row:
            name, other_way = self.apart(row[listed])
            if name in self.lists:
                spaces.append(self.but(self.lists[name], other_way))
            elif self.lists_known:
                #: An empty list matches nobody, and `!empty` matches everybody. That is the
                #: whole difference between a rule that lets the VPN through and one that,
                #: read wrongly, silently shuts every door the router keeps open.
                spaces.append(self.but(Space(), other_way))
            else:
                trouble = Said.of("rule.no-list", name=listed, list=name)
        if trouble:
            return Space.whole(), trouble
        if not spaces:
            return Space.whole(), None
        found = spaces[0]
        for space in spaces[1:]:
            found = found & space
        return found, None

    def ports(self, row: dict) -> tuple:
        text = row.get("dst-port", row.get("port", ""))
        try:
            return Space.ports(text), None
        except Unclear as error:
            return Space.ports(""), Said.of("rule.bad-condition", name="dst-port", why=error.said)

    def interfaces(self, row: dict, plain: str, listed: str) -> tuple:
        """The condition's interfaces. `!LAN` the router reads as "any but these" — so do we."""
        names, negated = set(), set()
        if plain in row:
            name, other_way = self.apart(row[plain])
            negated.add(other_way)
            names.add(name)
        if listed in row:
            name, other_way = self.apart(row[listed])
            negated.add(other_way)
            if name not in self.members:
                return None, Said.of("rule.no-list", name=listed, list=name)
            names |= self.members[name]
        if not names:
            return None, None
        if len(negated) > 1:
            return None, Said.of("rule.both-ways", name=plain, other=listed)
        return Faces(frozenset(names), inside=not negated.pop()), None


#: The two ends every castle has a road to. Keys, not names: the words are in the dictionary.
INTERNET, ROUTER = "internet", "router"
#: And a third end that is no end at all: a shout addressed to everybody and to nobody.
#: No castle stands there, no road leads there, and no cart ever sets out for it.
SHOUT = "shout"


@dataclass(frozen=True)
class Finding:
    """Something for the journal: worth a human's eye, even if the router is happy with it."""
    kind: str
    said: Said
    rules: tuple = ()


@dataclass(frozen=True)
class Roads:
    taken: str
    roads: tuple
    findings: tuple = ()
    #: What we set aside, and why. Passing over it in silence is not allowed.
    notes: tuple = ()

    @classmethod
    def of(cls, snapshot, network) -> "Roads":
        return _Builder(snapshot, network).build()

    def between(self, source: str, target: str):
        for road in self.roads:
            if road.source == source and road.target == target:
                return road
        return None


class _Builder:
    """One laying of roads: holds the snapshot, the castles and whatever turned up."""

    def __init__(self, snapshot, network):
        self.snapshot = snapshot
        self.network = network
        self.lists = self.address_lists()
        self.members = self.interface_lists()
        reader = Reader(self.lists, self.members,
                        lists_known="ip/firewall/address-list" not in snapshot.missing)
        rows = snapshot.rows("ip/firewall/filter")
        self.rules = reader.rules(rows, "forward") + reader.rules(rows, "input")
        self.forward = Chain([rule for rule in self.rules if rule.chain == "forward"])
        self.inward = Chain([rule for rule in self.rules if rule.chain == "input"])
        self.nat = reader.rules(snapshot.rows("ip/firewall/nat"), "srcnat")

    def build(self) -> Roads:
        roads = []
        for segment in self.network.segments:
            # The yard beyond the gate is a place to go to, never a place roads start from: who
            # may call out of it is decided by its own router, not by ours.
            if segment.outside:
                continue
            for other in self.network.segments:
                if segment.key != other.key:
                    roads.append(self.road(self.forward, segment.key, other.key, self.journey(segment, other)))
            roads.append(self.road(self.forward, segment.key, INTERNET, self.outward(segment)))
            roads.append(self.road(self.inward, segment.key, ROUTER, self.inward_journey(segment)))
        return Roads(self.snapshot.taken, tuple(roads), self.findings(roads), self.notes())

    def road(self, chain: Chain, source: str, target: str, journey: Journey) -> Road:
        road = chain.road(source, target, journey)
        renamed = tuple(rule.ref for rule in self.nat
                        if rule.action in NAT and rule.touches(journey))
        return replace(road, renamed=renamed) if renamed else road

    # --- from where to where --------------------------------------------------------------------
    def journey(self, segment, other) -> Journey:
        return Journey(Space.addresses(segment.network), Space.addresses(other.network),
                       frozenset([segment.key]), frozenset([other.key]))

    def outward(self, segment) -> Journey:
        """The road to the pier: everything that is not ours, leaving through the WAN list."""
        return Journey(Space.addresses(segment.network), Space.whole() - self.homeland(),
                       frozenset([segment.key]), frozenset(self.members.get(Network.WAN_LIST, ())))

    def inward_journey(self, segment) -> Journey:
        """The road to the customs house itself: the router's address here, the input chain."""
        return Journey(Space.addresses(segment.network), Space.addresses(segment.gateway),
                       frozenset([segment.key]), frozenset())

    def homeland(self) -> Space:
        found = Space()
        for segment in self.network.segments:
            found = found | Space.addresses(segment.network)
        return found

    # --- what can be seen from aside --------------------------------------------------------------
    def address_lists(self) -> dict:
        found: dict = {}
        for row in self.snapshot.rows("ip/firewall/address-list"):
            if row.get("disabled") == "true":
                continue
            try:
                space = Space.addresses(row.get("address", ""))
            except Unclear:
                continue
            found[row["list"]] = found.get(row["list"], Space()) | space
        return found

    def interface_lists(self) -> dict:
        found: dict = {}
        for row in self.snapshot.rows("interface/list/member"):
            found.setdefault(row["list"], set()).add(row["interface"])
        return found

    # --- findings ---------------------------------------------------------------------------------
    def findings(self, roads) -> tuple:
        found = [Finding("no-rule", Said.of("find.no-rule", source=road.source, target=road.target))
                 for road in roads if road.by_default and road.target != ROUTER]
        found += [Finding("mossy", Said.of("find.mossy", source=road.source, target=road.target),
                          tuple(rule for opening in road.openings for rule in opening.rules))
                  for road in roads if road.dead]
        found += [Finding("renamed", Said.of("find.renamed", source=road.source, target=road.target),
                          road.renamed) for road in roads if road.renamed and road.target != INTERNET]
        dead = tuple(rule.ref for rule in self.rules if not rule.disabled and rule.ref.packets == 0)
        if dead:
            found.append(Finding("dead-rule", Said.of("find.dead-rule", count=len(dead)), dead))
        off = tuple(rule.ref for rule in self.rules if rule.disabled)
        if off:
            found.append(Finding("switched-off", Said.of("find.switched-off", count=len(off)), off))
        nobody = tuple(rule.ref for rule in self.rules
                       if not rule.disabled and not (rule.source and rule.target))
        if nobody:
            found.append(Finding("nobody-rule", Said.of("find.nobody-rule", count=len(nobody)), nobody))
        puzzles = tuple(rule.ref for rule in self.rules if rule.unknown and not rule.disabled)
        if puzzles:
            found.append(Finding("puzzle", Said.of("find.puzzle", count=len(puzzles)), puzzles))
        return tuple(found)

    #: Tables that also decide a packet's fate. We do not count them — and we say so.
    BESIDE: ClassVar[dict] = {
        "ip/firewall/raw": Said.of("beside.raw"),
        "ip/firewall/mangle": Said.of("beside.mangle"),
    }

    def notes(self) -> tuple:
        said = []
        for path, why in self.BESIDE.items():
            rows = self.snapshot.tables.get(path)
            if rows is None:
                said.append(Said.of("note.no-table", path=path, why=why))
                continue
            deciding = [row for row in rows if row.get("action") not in PASSING]
            if deciding:
                said.append(Said.of("note.beside", path=path, count=len(deciding), why=why))
            elif rows:
                said.append(Said.of("note.beside-counters", path=path))
        policies = self.snapshot.tables.get("ip/ipsec/policy")
        if policies is not None:
            # The default template does not count as a policy: it protects nothing.
            alive = [row for row in policies if row.get("template") != "true"]
            said.append(Said.of("note.ipsec", count=len(alive)) if alive
                        else Said.of("note.ipsec-none"))
        for rule in self.rules:
            for reason in rule.aside:
                note = Said.of("note.rule", index=rule.index, why=reason)
                if note not in said:
                    said.append(note)
        for rule in self.rules:
            for reason in rule.unknown:
                note = Said.of("note.rule", index=rule.index, why=reason)
                if note not in said:
                    said.append(note)
        return tuple(said)

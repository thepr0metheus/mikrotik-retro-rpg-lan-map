"""The NAS's own gate: what DSM lets through once the router has let it.

A road on the map is the router's answer, and for most names it is the whole answer. But every
APP.lan.example is served by DSM's reverse proxy on the NAS, and DSM may ask again:

- an access profile on a name lets in only the networks it lists. The router lets the guests
  reach the NAS, and DSM still answers them 403 for that name;
- a name the proxy leads on to another machine is a way past the router. Whoever may reach the
  NAS reaches that machine too, so long as the NAS itself may — even from a network the router
  keeps away from it.

DSM's own firewall would be a third check. It is read as well: whether it is on, and how many
rules it holds. The map does not read those rules one by one, and when there are any it says so
rather than pass the gate off as what the proxy alone makes it.

Two halves, as with the containers, and one file between them, data/containers.json:

- GateReader, in the watcher, reads DSM's files through read-only mounts: the reverse proxy's
  nginx configuration and the firewall's settings. Only names, the ports the proxy listens on,
  where each name leads and its allow and deny lines are copied: no certificate, no header.
- Gate, on the map's side, tells them against the router's roads: for every name, which of the
  networks that reach the NAS DSM turns away, and which get past a road the router keeps shut.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlsplit

from .spans import ANY_PORT, NO_PORTS, Space, Unclear
from .tongue import Said, Tongue


class ProxyRules:
    """The server blocks of DSM's reverse proxy, read the way nginx reads the file DSM writes.

    DSM writes one block per rule: the ports it listens on, the name, the access profile as an
    include, and one location that passes everything on. Lines inside a location other than
    proxy_pass are not ours to read: the error page's own `allow all` lets the error page be
    shown, not the name be reached."""

    #: Where nginx finds the reverse proxy: a link into sites-available, written by DSM.
    FILE: ClassVar[str] = "sites-enabled/server.ReverseProxy.conf"
    #: `listen 443 ssl;` — the `[::]:443` twin is the same port, for IPv6, and is not counted twice.
    LISTEN: ClassVar = re.compile(r"^listen\s+(\d+)\b")
    NAME: ClassVar = re.compile(r"^server_name\s+([^;]+);")
    PASS: ClassVar = re.compile(r"^proxy_pass\s+([^;\s]+)\s*;")
    #: `include conf.d/.acl.<id>.conf*;` — the star lets nginx start when the file is gone.
    PROFILE: ClassVar = re.compile(r"^include\s+(conf\.d/\.acl\.[^;*\s]+)\*?\s*;")
    RULE: ClassVar = re.compile(r"^(allow|deny)\s+([^;\s]+)\s*;")

    @classmethod
    def blocks(cls, text: str) -> list:
        """Every `server { … }` with a place to pass to: its names, ports, target and profile."""
        found, block, depth = [], None, 0
        for raw in text.splitlines():
            line = raw.strip()
            if depth == 0 and line.startswith("server") and line.endswith("{"):
                block = {"names": [], "ports": [], "to": "", "profile": ""}
            elif block is not None:
                cls.read(block, line)
            depth += line.count("{") - line.count("}")
            if block is not None and depth == 0:
                if block["to"]:
                    found.append(block)
                block = None
        return found

    @classmethod
    def read(cls, block: dict, line: str) -> None:
        if (listen := cls.LISTEN.match(line)) and int(listen.group(1)) not in block["ports"]:
            block["ports"].append(int(listen.group(1)))
        elif name := cls.NAME.match(line):
            block["names"] += name.group(1).split()
        elif (target := cls.PASS.match(line)) and not block["to"]:
            block["to"] = target.group(1)
        elif profile := cls.PROFILE.match(line):
            block["profile"] = profile.group(1)

    @classmethod
    def rules(cls, text: str) -> list:
        """An access profile's lines in their order: [["allow", "192.168.88.0/24"], ["deny", "all"]]."""
        found = []
        for line in text.splitlines():
            if rule := cls.RULE.match(line.strip()):
                found.append([rule.group(1), rule.group(2)])
        return found


@dataclass(frozen=True)
class GateReader:
    """The watcher's reading of DSM's gate, through read-only mounts of DSM's own folders.

    The folders are mounted at the paths they have on the NAS: DSM's links point there."""

    nginx: Path
    firewall: Path

    #: What "unread" is called in a door's profile: the file is named but would not open.
    UNREAD: ClassVar[str] = "unread"

    def read(self) -> dict:
        doors, missing = self.doors()
        return {"missing": missing, "doors": doors, "firewall": self.wall()}

    def doors(self) -> tuple:
        """Every name the proxy serves, once: blocks for one name and one target are one door."""
        if not self.nginx.is_dir():
            return [], "gate.not-mounted"
        try:
            text = (self.nginx / ProxyRules.FILE).read_text(encoding="utf-8")
        except FileNotFoundError:
            return [], "gate.no-proxy"
        except (OSError, UnicodeDecodeError):
            return [], "gate.unreadable"
        found: dict = {}
        for block in ProxyRules.blocks(text):
            profile = self.profile(block["profile"])
            for name in block["names"]:
                key = (name, block["to"], json.dumps(profile))
                door = found.setdefault(key, {"name": name, "ports": [], "to": block["to"], "profile": profile})
                door["ports"] = sorted(set(door["ports"]) | set(block["ports"]))
        return sorted(found.values(), key=lambda door: (door["name"], door["ports"])), ""

    def profile(self, include: str):
        """No include is no profile: everyone the router lets through. A profile named but
        unreadable is said to be unread — never taken for "everyone"."""
        if not include:
            return None
        try:
            return ProxyRules.rules((self.nginx / include).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return self.UNREAD

    def wall(self) -> dict:
        """DSM's firewall: on or off, its profile, and how many rules that profile holds."""
        if not self.firewall.is_dir():
            return {"missing": "gate.firewall-not-mounted"}
        try:
            settings = json.loads((self.firewall / "firewall_settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"missing": "gate.firewall-unreadable"}
        profile = str(settings.get("profile", ""))
        rules = None
        for file in sorted(self.firewall.glob("*.json")):
            try:
                written = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(written, dict) and written.get("name") == profile and "rules" in written:
                rules = len(written["rules"] or [])
        return {"missing": "", "on": bool(settings.get("status")), "profile": profile, "rules": rules}


@dataclass(frozen=True)
class Door:
    """One name the proxy serves, as the map tells it."""

    name: str
    ports: tuple
    to: str
    #: None: no profile. A tuple of (action, source): the profile's lines. "unread": not readable.
    profile: object

    #: Names that mean "this very machine" in a proxy target.
    LOCAL: ClassVar[tuple] = ("localhost", "127.0.0.1", "::1")

    @classmethod
    def of(cls, written: dict) -> "Door":
        profile = written.get("profile")
        return cls(str(written.get("name", "")), tuple(written.get("ports") or ()), str(written.get("to", "")),
                   tuple(tuple(rule) for rule in profile) if isinstance(profile, list) else profile)

    @property
    def backend(self) -> tuple:
        """Where the name leads: its host, and the port, by the scheme when none is written."""
        parts = urlsplit(self.to)
        try:
            port = parts.port
        except ValueError:
            port = None
        return parts.hostname or "", port or (443 if parts.scheme == "https" else 80)

    def local(self, here: str) -> bool:
        """Whether the name stays on the NAS: a target on the NAS is no way past anything."""
        host = self.backend[0]
        return host in self.LOCAL or (bool(here) and host == here)

    def admitted(self, space: Space):
        """The part of `space` the profile lets in, nginx's way: the first line that matches an
        address decides, and an address no line matches is let in.

        An IPv6 line or a `unix:` one cannot match an IPv4 address, and is passed over. A line
        that is neither makes the answer None — unread — rather than a guess."""
        if self.profile is None:
            return space
        if not isinstance(self.profile, tuple):
            return None
        left, allowed = space, Space()
        for action, source in self.profile:
            if ":" in source:
                continue
            try:
                hit = left & (Space.whole() if source == "all" else Space.addresses(source))
            except Unclear:
                return None
            if action == "allow":
                allowed = allowed | hit
            left = left - hit
        return allowed | left


@dataclass(frozen=True)
class Gate:
    """The NAS's gate told against the router's roads, for the map and for the text."""

    doors: tuple
    firewall: dict
    #: Why there is nothing to tell: a code. "" when the watcher read DSM's files.
    missing: str
    taken: str
    stale: bool
    segments: tuple
    roads: object
    #: The NAS's address: where the proxy listens. "" when the map could not tell its own.
    here: str

    #: The port DSM's proxy listens on when a door names none.
    HTTPS: ClassVar[int] = 443

    @classmethod
    def of(cls, containers, network, roads, here: str) -> "Gate":
        """From the watcher's snapshot, whatever state it is in."""
        payload = containers.payload
        written = (payload or {}).get("gate")
        if payload is None:
            missing = "gate.no-snapshot"
        elif not isinstance(written, dict):
            missing = "gate.not-read"
        else:
            missing = written.get("missing") or ""
        written = written if isinstance(written, dict) else {}
        return cls(tuple(Door.of(door) for door in written.get("doors") or []), written.get("firewall") or {},
                   missing, (payload or {}).get("taken", ""), containers.stale, tuple(network.segments), roads,
                   here)

    def payload(self, tongue: Tongue) -> dict:
        return {"missing": self.missing, "taken": self.taken, "stale": self.stale, "here": self.here,
                "home": self.home.key if self.home else "", "firewall": self.firewall,
                "wall": tongue.tell(self.wall()), "doors": [self.door(door) for door in self.doors]}

    def wall(self) -> Said:
        """DSM's firewall in one sentence: off; on, with rules the map does not read; not known."""
        if self.firewall.get("missing") is None:
            return Said.of("gate.firewall-unreadable")
        if self.firewall["missing"]:
            return Said.of(self.firewall["missing"])
        if self.firewall.get("on"):
            rules = self.firewall.get("rules")
            return Said.of("gate.firewall.on", profile=self.firewall.get("profile") or "?",
                           rules="?" if rules is None else rules)
        return Said.of("gate.firewall.off")

    @property
    def home(self):
        """The NAS's own network: neighbours there reach it without the router."""
        return next((segment for segment in self.segments if segment.holds(self.here)), None)

    def door(self, door: Door) -> dict:
        """One name: who of those reaching the NAS DSM turns away, and who gets past the router."""
        host, port = door.backend
        local = door.local(self.here)
        beyond = None if local else next((segment for segment in self.segments if segment.holds(host)), None)
        told = {"name": door.name, "ports": list(door.ports), "to": f"{host}:{port}", "local": local,
                "beyond": beyond.key if beyond else "",
                "profile": [list(rule) for rule in door.profile] if isinstance(door.profile, tuple) else door.profile,
                "refuses": [], "past": [], "unclear": []}
        if not self.here:
            return told
        onward = not local and beyond is not None and bool(self.reach(self.home, (port,), host, self.here))
        for segment in self.segments:
            whole = Space.addresses(segment.network)
            arrive = self.reach(segment, door.ports or (self.HTTPS,), self.here)
            if arrive is None:
                told["unclear"].append(segment.key)
                continue
            admitted = door.admitted(arrive)
            if admitted is None:
                told["unclear"].append(segment.key)
                continue
            if arrive - admitted:
                told["refuses"].append(self.part(segment, arrive - admitted, whole))
            if onward:
                direct = self.reach(segment, (port,), host)
                if direct is None:
                    told["unclear"].append(segment.key)
                elif admitted - direct:
                    told["past"].append(self.part(segment, admitted - direct, whole))
        return told

    @staticmethod
    def part(segment, space: Space, whole: Space) -> dict:
        return {"segment": segment.key, "whole": space == whole, "space": space.address_text()}

    def reach(self, segment, ports: tuple, target: str, source: str = ""):
        """Which addresses of `segment` the router lets start a TCP connection to `target` on any
        of `ports` — or only `source`, when one is named. None when a rule on the way is unread.

        Neighbours in one network talk past the router, and it is not asked."""
        if segment is None:
            return Space()
        whole = Space.addresses(source) if source else Space.addresses(segment.network)
        if segment.holds(target):
            return whole
        other = next((one for one in self.segments if one.holds(target)), None)
        road = self.roads.between(segment.key, other.key) if other else None
        if road is None:
            return Space()
        if road.puzzles:
            return None
        found = Space()
        aim = Space.addresses(target)
        for opening in road.openings:
            if opening.protocol not in ("tcp", "any") or not Space(opening.target_spans).overlaps(aim):
                continue
            if any(port in self.ports(opening.ports) for port in ports):
                found = found | Space(opening.source_spans)
        return found & whole

    @staticmethod
    def ports(text: str) -> Space:
        """An opening's ports, as the road says them: every port, none, or a list."""
        if text == ANY_PORT:
            return Space.ports("")
        if text == NO_PORTS:
            return Space()
        return Space.ports(text)

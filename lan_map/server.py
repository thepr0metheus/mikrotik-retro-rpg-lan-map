"""The HTTP side: the page's files, the map in one lump, and the layout dragged by a mouse.

The map never changes the network. The only thing it writes is where things stand on the
canvas: a file next to the snapshot. It goes to the router to read, and only on Refresh.

Every answer with words in it takes a language. `?lang=` decides, failing that the browser's
own Accept-Language, failing that English. The page asks for the language its reader chose,
and it remembers that choice itself.
"""
from __future__ import annotations

import json
import logging
import re
import socket
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .api_spec import ApiSpec
from .atlas import Atlas
from .containers import Containers, docker_time
from .listening import Listening
from .audience import Audience, AudienceError
from .layout import Layout, LayoutError
from .memory import Memory
from .model import Network
from .names import Names
from .destinations import Destinations
from .gate import Gate
from .ports import Knocker, Locked
from .packages import InstalledPackages
from .refresh import Refresh
from .scribe import Scribe, guide
from .settings import SettingsError
from .snapshot import Snapshot, utc_now
from .specs import CardRefused, CardText, Specs, SpecsText
from .sprites import Sprites
from .tongue import Said, Tongue, known
from .view import View

log = logging.getLogger("lan_map")


class Refusal(Exception):
    """A refusal: raised anywhere, sent exactly once in dispatch.

    The reason travels as a phrase, not as words: which language it is said in is decided by
    the request, and the request is only read at the very edge."""

    def __init__(self, status: int, said: Said, **extra):
        super().__init__(said.key)
        self.status = status
        self.said = said
        self.extra = extra

    def body(self, tongue: Tongue) -> dict:
        return {"error": tongue.tell(self.said), **self.extra}


class MapApp:
    """Everything a request may need in one place: files, snapshot, atlas, layout."""

    TYPES = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }
    BODY_MOST = 128 * 1024
    #: How old a snapshot may be when somebody opens the map. Nothing on a schedule asks the
    #: router, so an older one the page asks anew by itself, as the Refresh button does.
    ASK_AFTER = timedelta(minutes=10)

    def __init__(self, web_dir: Path, data_dir: Path, doorman, take=None, sprites=None,
                 audience=None, knocker=None, ask=None, clock=utc_now, here=None, proc_net=None,
                 packages=None):
        self.web_dir = Path(web_dir).resolve()
        self.data_dir = Path(data_dir)
        self.doorman = doorman
        self.audience = audience
        self.sprites = sprites or Sprites.read()
        #: Who knocks on a device's doors. Replaced in tests so as not to go into the network.
        self.knocker = knocker or Knocker()
        #: What takes a fresh snapshot. None means no router password, and Refresh says so.
        self.take = take
        #: What reads one table from the router, for the rounds lighter than a snapshot.
        self.ask = ask
        self.clock = clock
        #: The map's own address: which house on the map it lives in. "" when unknown.
        self.here = here or (lambda: "")
        #: Where the kernel keeps the host's TCP tables: /proc/net, since the map lives in the
        #: host's network. None: nowhere to look, and the free port says it was not checked.
        self.proc_net = proc_net
        #: What this copy is made of, for a check of known vulnerabilities.
        self.packages = packages or InstalledPackages()
        #: The names the router gave before. Replaced whole, never changed in place: the rounds
        #: write it under the lock, the page's threads only ever read the current one.
        self.memory = self.recall()
        self.remembering = threading.Lock()
        #: One card written at a time: two writers reading the same file would lose a line.
        self.carding = threading.Lock()
        #: One walk to the router at a time: the rounds, the button and every reader share it.
        self.walking = threading.Lock()

    # --- what the map knows ---------------------------------------------------------------------
    @property
    def snapshot_path(self) -> Path:
        return self.data_dir / "snapshot.json"

    @property
    def layout_path(self) -> Path:
        return self.data_dir / "layout.json"

    @property
    def atlas_path(self) -> Path:
        return self.data_dir / "atlas.json"

    @property
    def names_path(self) -> Path:
        return self.data_dir / "names.json"

    @property
    def specs_path(self) -> Path:
        """The cards of characteristics: what each device is made of, as somebody wrote it."""
        return self.data_dir / "specs.json"

    @property
    def containers_path(self) -> Path:
        """Written by the container watcher, a service of its own: the map only reads it."""
        return self.data_dir / "containers.json"

    def containers(self) -> Containers:
        return Containers.read(self.containers_path, self.clock())

    def listening(self) -> Listening:
        """What listens on the host at this moment: only the free port asks, so only it reads."""
        return Listening.read(self.proc_net)

    @staticmethod
    def address_toward(host: str) -> str:
        """This machine's own address on its way to `host`. Nothing is sent: connecting a UDP
        socket only picks the route, and the route names the address the host is reached from."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect((host, 9))
                address = probe.getsockname()[0]
        except OSError:
            return ""
        # Loopback is no house on the map: it only means the route could not be told.
        return "" if address.startswith("127.") or address == "0.0.0.0" else address

    @property
    def version(self) -> str | None:
        """The commit this copy was built from. git archive writes it into VERSION; a working
        copy still holds the placeholder, and then there is no version to name."""
        try:
            text = (self.web_dir.parent / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return None if not text or text.startswith("$Format") else text

    # --- the names the router gave before -------------------------------------------------------
    def recall(self) -> Memory:
        """The memory as it lies on disk.

        A file that cannot be read is set aside rather than written over: it may be the only
        copy of two weeks of names, and a person may want to look at why it broke."""
        try:
            return Memory.read(self.names_path)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            aside = self.names_path.with_name(self.names_path.name + ".unreadable")
            log.warning("the memory of names could not be read (%s); set aside as %s", error, aside)
            try:
                self.names_path.replace(aside)
            except OSError:
                pass
            return Memory()

    def remember(self, *readings) -> int:
        """Readings of the router's DNS cache, each a (rows, when) pair, into the memory at once.

        Returns how many addresses are new to it."""
        with self.remembering:
            known = self.memory.names
            memory = self.memory
            for rows, seen in readings:
                memory = memory.learned(rows, seen)
            memory = memory.forgotten(self.clock())
            memory.write(self.names_path)
            self.memory = memory
            return len(set(memory.names) - set(known))

    def remember_stored(self) -> int:
        """Whatever the stored snapshots saw, into the memory, oldest first.

        Run at start: the shelf holds hours of the router's answers, and a memory begun from
        them has something to say at once rather than in a week. Reading them again on the
        next start changes nothing that is fresher."""
        stored = []
        for path in Snapshot.stored(self.snapshot_path):
            try:
                stored.append(Snapshot.read(path))
            except (OSError, ValueError, KeyError) as error:
                log.warning("a stored snapshot could not be read for names: %s (%s)", path, error)
        self.remember(*((snapshot.tables.get(Memory.CACHE, []), snapshot.taken)
                        for snapshot in sorted(stored, key=lambda one: one.taken)))
        return len(self.memory.names)

    def remember_names(self) -> dict:
        """One look into the router's DNS cache, and whatever is in it written down.

        Far lighter than a snapshot: one table, nothing drawn, nothing put on the shelf. Its
        rounds catch names that expire between snapshots; they are off unless
        LAN_MAP_NAMES_MINUTES switches them on, since each look is a login the router logs."""
        if self.ask is None:
            raise Refusal(503, Said.of("refuse.no-password"))
        try:
            rows = self.ask(Memory.CACHE)
        except SettingsError as error:  # no password: a missing setting, not a broken router
            raise Refusal(503, error.said) from error
        except Exception as error:      # the router refused, or did not answer at all
            raise Refusal(502, Said.of("refuse.router-gave-nothing",
                                       why=getattr(error, "said", error))) from error
        new = self.remember((rows, self.clock().isoformat(timespec="seconds")))
        return {"names": len(self.memory.names), "new": new}

    def watchers(self) -> dict:
        return {"show": [str(network) for network in
                         (self.audience.networks() if self.audience else self.doorman.show())]}

    def choose_watchers(self, texts, keeper: str) -> dict:
        if self.audience is None:
            raise Refusal(503, Said.of("refuse.watchers-from-env"))
        try:
            self.audience.choose(texts, keeper)
        except AudienceError as error:
            raise Refusal(400, error.said) from error
        except OSError as error:
            raise Refusal(500, Said.of("refuse.settings-not-saved",
                                       why=error.strerror or error)) from error
        return self.watchers()

    def view(self, at: str = "", tongue: Tongue | None = None) -> dict:
        """The picture from the latest snapshot, or from one that lies on the shelf.

        No snapshot means we say so, rather than draw emptiness."""
        path, before = self.snapshot_path, Snapshot.before(self.snapshot_path)
        if at:
            shelf = {kept.name: kept for kept in self.history_files()}
            if at not in shelf:
                raise Refusal(404, Said.of("refuse.no-such-snapshot"))
            older = sorted(shelf)[:list(sorted(shelf)).index(at)]
            path, before = shelf[at], (shelf[older[-1]] if older else Path("none"))
        snapshot = self.opened(path)
        older = Snapshot.read(before) if before.is_file() else None
        view = View.of(snapshot, Atlas.read(self.atlas_path), before=older,
                       tongue=tongue or Tongue.of(), memory=self.memory)
        # The NAS's own gate, told against these very roads. Its rules are the watcher's latest
        # reading, whichever snapshot of the router is being looked at.
        gate = Gate.of(self.containers(), view.network, view.roads, self.here())
        payload = view.payload()
        return {**payload, "devices": self.carded(payload["devices"], view.tongue),
                "gate": gate.payload(view.tongue), "refresh_on_open": not at and self.old(snapshot)}

    def carded(self, devices: list, tongue: Tongue) -> list:
        """Each device with its card in words: lines, none for no card, None when the cards do
        not read — that is not the same as nobody having written one."""
        try:
            specs = Specs.read(self.specs_path)
        except (OSError, ValueError) as error:
            log.warning("specs.json does not read: %s", error)
            return [{**device, "specs": None} for device in devices]
        return [{**device, "specs": CardText(specs.found(device["key"], *(seat["ip"] for seat in device["seats"]))[1],
                                             tongue).lines()} for device in devices]

    def old(self, snapshot: Snapshot) -> bool:
        """Older than ASK_AFTER, or of no readable time: the page asks for a fresh one on opening."""
        taken = docker_time(snapshot.taken)
        return taken is None or self.clock() - taken > self.ASK_AFTER

    @staticmethod
    def opened(path: Path) -> Snapshot:
        """A snapshot from disk, or the refusal that says why there is none to look at."""
        if not path.is_file():
            raise Refusal(503, Said.of("refuse.no-snapshot-yet"))
        try:
            return Snapshot.read(path)
        except (OSError, ValueError, KeyError) as error:
            raise Refusal(500, Said.of("refuse.snapshot-unreadable", why=error)) from error

    def doors(self, ip: str) -> dict:
        """Which of a device's doors stand open.

        We knock only at addresses the map already knows: otherwise it would become a handy
        way of knocking from somewhere else, and that is none of its business."""
        if ip not in self.addresses():
            raise Refusal(404, Said.of("refuse.no-such-device"))
        try:
            return self.knocker.open_doors(ip)
        except Locked as error:
            raise Refusal(400, error.said) from error

    def addresses(self) -> set:
        return {seat["ip"] for device in self.view()["devices"] for seat in device["seats"]}

    def story(self, at: str = "", tongue: Tongue | None = None) -> str:
        """The same picture in words. A drawing cannot be retold — so it comes from the same lump."""
        tongue = tongue or Tongue.of()
        return Scribe.of(self.view(at, tongue), tongue).markdown()

    def history_files(self) -> list:
        shelf = Snapshot.shelf(self.snapshot_path)
        return sorted(shelf.glob("*.json")) if shelf.is_dir() else []

    def history(self) -> dict:
        """What lies on the shelf: the file name and when it was taken, freshest first."""
        return {"kept": [{"name": path.name, "taken": self.when(path.stem)}
                         for path in reversed(self.history_files())]}

    @staticmethod
    def when(name: str) -> str:
        """From a file name back into a time: 2026-09-20T08-25-23 → 2026-09-20T08:25:23."""
        day, _, clock = name.partition("T")
        return f"{day}T{clock.replace('-', ':')}" if clock else name

    def layout(self) -> Layout:
        try:
            return Layout.read(self.layout_path)
        except LayoutError as error:
            raise Refusal(500, error.said) from error

    def move(self, places, looks=None, size=None) -> Layout:
        try:
            layout = Layout(Layout.checked(places), Layout.checked_looks(looks or {}),
                            Layout.checked_field(size or []))
        except LayoutError as error:
            raise Refusal(400, error.said) from error
        try:
            layout.write(self.layout_path)
        except OSError as error:
            raise Refusal(500, Said.of("refuse.layout-not-saved",
                                       why=error.strerror or error)) from error
        return layout

    NAME_MOST = 48
    COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")

    def name_device(self, device: str, fields: dict) -> dict:
        """A device's name and kind are a human's choice. A kind with no picture is refused."""
        kind = fields.get("kind")
        name = fields.get("name")
        if kind and not self.sprites.has(kind):
            raise Refusal(400, Said.of("refuse.no-such-kind", kind=kind))
        if name and len(name) > self.NAME_MOST:
            raise Refusal(400, Said.of("refuse.name-too-long", most=self.NAME_MOST))
        atlas = Atlas.read(self.atlas_path).with_device(device, **fields)
        try:
            atlas.write(self.atlas_path)
        except OSError as error:
            raise Refusal(500, Said.of("refuse.atlas-not-saved",
                                       why=error.strerror or error)) from error
        entry = atlas.device(device)
        return {"device": device, "name": entry.get("name", ""), "kind": entry.get("kind", ""),
                "hidden": bool(entry.get("hidden")), "pinned": bool(entry.get("pinned"))}

    def houses(self, tongue: Tongue | None = None) -> dict:
        """Who the house is talking to out there: known, and how; and whoever is not known.

        From the snapshot the map itself is drawn from, so a reader looks at their own network
        rather than at an example. Two empty lists may mean nobody is out there, or that there
        is nothing to look at — no snapshot, or no connection table in it — and those are told
        apart: `missing` says why, and is empty only when the lists are the truth."""
        tongue = tongue or Tongue.of()
        try:
            view = self.view(tongue=tongue)
        except Refusal as refusal:
            return {**Destinations().payload(), "taken": "", "missing": tongue.tell(refusal.said)}
        traffic = view.get("traffic", {})
        return {**Destinations.of(traffic.get("trips", {})).payload(), "taken": view.get("taken", ""),
                "missing": traffic.get("missing", "")}

    def names(self, tongue: Tongue | None = None) -> dict:
        """The names the router answers itself, and where each of them leads.

        From the snapshot the map itself is drawn from. As on the page of services, empty
        lists come with the reason when there was nothing to read: "the router holds no names"
        and "nothing was read" are never the same answer."""
        tongue = tongue or Tongue.of()
        try:
            snapshot = self.opened(self.snapshot_path)
        except Refusal as refusal:
            return {**Names().payload(), "taken": "", "missing": tongue.tell(refusal.said)}
        names = Names.of(snapshot, Network.of(snapshot, Atlas.read(self.atlas_path)))
        return {**names.payload(), "taken": snapshot.taken, "missing": ""}

    def read_specs(self) -> Specs:
        """The cards on disk. A file that does not read is refused, never shown as no cards."""
        try:
            return Specs.read(self.specs_path)
        except (OSError, ValueError) as error:
            raise Refusal(500, Said.of("refuse.specs-unreadable", why=error)) from error

    def specs(self, tongue: Tongue | None = None) -> dict:
        """Every device on the map with its card. With no snapshot the cards still stand, and
        the reason the map's own devices are missing is said."""
        tongue = tongue or Tongue.of()
        specs, atlas = self.read_specs(), Atlas.read(self.atlas_path)
        try:
            snapshot = self.opened(self.snapshot_path)
        except Refusal as refusal:
            devices, taken, missing = (), "", tongue.tell(refusal.said)
        else:
            devices, taken, missing = Network.of(snapshot, atlas).devices, snapshot.taken, ""
        return {"taken": taken, "missing": missing, "fields": Specs.described(), "name_most": self.NAME_MOST,
                "devices": specs.listed(devices, atlas, tongue)}

    def specs_text(self, tongue: Tongue) -> str:
        answer = self.specs(tongue)
        return SpecsText(answer["devices"], tongue, answer["missing"]).markdown()

    def write_card(self, device: str, fields: dict, name, by, asker, tongue: Tongue) -> dict:
        """One device's card written, and its name on the map when one is sent.

        From the networks that may move things, any device's card and name. From any other
        network the map is shown to, only the asking device's own card — an agent writing down
        the machine it runs on — and never the name: the name on the map is the owner's choice."""
        try:  # refused before anything is written: a name changed for a card refused is half a write
            Specs.clean(fields)
            Specs.signed(by)
        except CardRefused as refused:
            raise Refusal(400, refused.said) from refused
        try:
            devices = Network.of(self.opened(self.snapshot_path), Atlas.read(self.atlas_path)).devices
        except Refusal:
            devices = ()
        known = next((one for one in devices
                      if device == one.key or device in (seat.ip for seat in one.seats)), None)
        keys = (known.key, *(seat.ip for seat in known.seats)) if known else (device,)
        if known is None and not self.read_specs().found(device)[0]:
            raise Refusal(404, Said.of("refuse.specs-no-such-device", device=device))
        if not asker.allowed:
            if asker.address not in keys[1:]:
                raise Refusal(403, Said.of("refuse.specs-own-only", address=asker.address or "?"))
            if name is not None:
                raise Refusal(403, Said.of("refuse.specs-name-owner"))
        if name is not None:
            self.name_device(keys[0], {"name": name})
        if fields:
            with self.carding:
                changed = self.read_specs().with_card(keys, fields, by, self.clock().isoformat(timespec="seconds"))
                try:
                    changed.write(self.specs_path)
                except OSError as error:
                    raise Refusal(500, Said.of("refuse.specs-not-saved", why=error.strerror or error)) from error
        return next(one for one in self.specs(tongue)["devices"] if one["device"] == keys[0])

    #: A port's place and the port, as a line of access writes them: "router udp 67-68",
    #: "192.168.20.10 tcp 443", "192.168.20.x tcp 25565-25567", or a machine alone.
    PORT_KEY = re.compile(r"(router|\d{1,3}\.\d{1,3}\.\d{1,3}\.(\d{1,3}|x))( [a-z0-9-]{1,16}( \d[\d, -]{0,40})?)?")
    NOTE_MOST = 200

    def note_port(self, key: str, note: str) -> dict:
        """What a port is for, in the owner's words: the atlas keeps it beside the names."""
        key, note = key.strip(), " ".join(note.split())
        if not self.PORT_KEY.fullmatch(key):
            raise Refusal(400, Said.of("refuse.not-a-port", port=key))
        if len(note) > self.NOTE_MOST:
            raise Refusal(400, Said.of("refuse.note-too-long", most=self.NOTE_MOST))
        atlas = Atlas.read(self.atlas_path).with_port(key, note)
        try:
            atlas.write(self.atlas_path)
        except OSError as error:
            raise Refusal(500, Said.of("refuse.atlas-not-saved",
                                       why=error.strerror or error)) from error
        return {"key": key, "note": atlas.ports.get(key, "")}

    def name_segment(self, key: str, fields: dict) -> dict:
        """A castle's name and colour. A colour is six hex digits, or the map turns gaudy."""
        title = fields.get("title")
        colour = fields.get("colour")
        if title and len(title) > self.NAME_MOST:
            raise Refusal(400, Said.of("refuse.name-too-long", most=self.NAME_MOST))
        if colour and not self.COLOUR.match(colour):
            raise Refusal(400, Said.of("refuse.not-a-colour", colour=colour))
        atlas = Atlas.read(self.atlas_path).with_segment(key, **fields)
        try:
            atlas.write(self.atlas_path)
        except OSError as error:
            raise Refusal(500, Said.of("refuse.atlas-not-saved",
                                       why=error.strerror or error)) from error
        entry = atlas.segments.get(key, {})
        return {"segment": key, "title": entry.get("title", ""), "colour": entry.get("colour", "")}

    def refresh(self) -> dict:
        """A walk to the router for a fresh snapshot, for the rounds. One at a time: two walks at
        once would only ask the router the same thing twice."""
        with self.walking:
            return self.walk()

    def refreshed(self, since: datetime) -> dict:
        """The router's snapshot taken at `since` or later: a walk only when the latest is older.

        Whoever asks while a walk is under way waits for it, and then finds it fresh enough. This
        never raises: a walk that failed comes back with its reason, `why`, as a phrase."""
        with self.walking:
            try:
                latest = Snapshot.read(self.snapshot_path) if self.snapshot_path.is_file() else None
            except (OSError, ValueError, KeyError):
                latest = None
            taken = docker_time(latest.taken) if latest else None
            if taken is not None and taken >= since:
                return {"taken": latest.taken, "walked": False, "why": None}
            try:
                return {**self.walk(), "walked": True, "why": None}
            except Refusal as refusal:
                return {"taken": latest.taken if latest else "", "walked": True, "why": refusal.said}

    def walk(self) -> dict:
        """The walk itself: the router's tables, written whole beside the previous snapshot."""
        if self.take is None:
            raise Refusal(503, Said.of("refuse.no-password"))
        try:
            snapshot = self.take()
        except SettingsError as error:  # no password: a missing setting, not a broken router
            raise Refusal(503, error.said) from error
        except Exception as error:      # the router refused, or did not answer at all
            log.warning("the snapshot failed: %s", error)
            raise Refusal(502, Said.of("refuse.router-gave-nothing",
                                       why=getattr(error, "said", error))) from error
        snapshot.write(self.snapshot_path)
        try:
            self.remember((snapshot.tables.get(Memory.CACHE, []), snapshot.taken))
        except OSError as error:        # the snapshot is taken; a name lost is no reason to say otherwise
            log.warning("the names from the snapshot were not remembered: %s", error)
        return {"taken": snapshot.taken, "missing": snapshot.missing}

    def langs(self) -> dict:
        """Which languages are on the shelf. A new one is a new file in web/lang."""
        return {"langs": [dict(one) for one in known()], "default": Tongue.of().code}

    # --- the page's files -----------------------------------------------------------------------
    def static_file(self, raw_path: str):
        path = unquote(urlsplit(raw_path).path)
        if path.endswith("/"):
            path += "index.html"
        parts = [part for part in path.split("/") if part]
        if not parts or any(part.startswith(".") or "\\" in part for part in parts):
            return None
        candidate = self.web_dir.joinpath(*parts).resolve()
        if not candidate.is_relative_to(self.web_dir) or not candidate.is_file():
            return None
        if candidate.suffix.lower() not in self.TYPES:
            return None
        return candidate

    def make_server(self, host: str, port: int) -> ThreadingHTTPServer:
        handler = type("BoundHandler", (RequestHandler,), {"app": self})
        server = ThreadingHTTPServer((host, port), handler)
        server.daemon_threads = True
        return server


class RequestHandler(BaseHTTPRequestHandler):
    app: MapApp  # handed in by the server in make_server

    server_version = "lan-map"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 30

    ROUTES = {
        ("GET", "/api/map"): "get_map",
        ("GET", "/api/history"): "get_history",
        ("GET", "/api/langs"): "get_langs",
        ("GET", "/network.md"): "get_story",
        ("GET", "/llms.txt"): "get_guide",
        ("GET", "/api/layout"): "get_layout",
        ("PUT", "/api/layout"): "put_layout",
        ("PUT", "/api/device"): "put_device",
        ("PUT", "/api/segment"): "put_segment",
        ("PUT", "/api/port"): "put_port",
        ("GET", "/api/houses"): "get_houses",
        ("GET", "/api/names"): "get_names",
        ("GET", "/containers.md"): "get_containers_text",
        ("GET", "/api/containers"): "get_containers",
        ("GET", "/specs.md"): "get_specs_text",
        ("GET", "/api/specs"): "get_specs",
        ("PUT", "/api/specs"): "put_specs",
        ("GET", "/api/settings"): "get_settings",
        ("PUT", "/api/settings"): "put_settings",
        ("POST", "/api/refresh"): "post_refresh",
        ("POST", "/api/ports"): "post_ports",
        ("GET", "/healthz"): "health",
        ("GET", "/api/packages"): "get_packages",
        ("GET", "/openapi.json"): "get_openapi",
    }
    #: Scripts: our own files only. Styles are allowed inside the page too: the hint is placed
    #: under the cursor by coordinates, and that is an inline style. The page loads nothing else.
    CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
    QUIET = ("/healthz",)

    def do_GET(self):
        self.dispatch("GET")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_POST(self):
        self.dispatch("POST")

    def asked(self, name: str, fallback: str = "") -> str:
        return parse_qs(urlsplit(self.path).query).get(name, [fallback])[0]

    def tongue(self) -> Tongue:
        """The language of this answer: `?lang=`, then the browser's list, then English."""
        return Tongue.asked(self.asked("lang"), self.headers.get("Accept-Language", ""))

    def dispatch(self, method: str) -> None:
        path = urlsplit(self.path).path
        self.body_read = False
        try:
            route = self.ROUTES.get((method, path))
            if route is not None:
                getattr(self, route)()
            elif any(path == route for _, route in self.ROUTES):
                raise Refusal(405, Said.of("refuse.wrong-method"))
            elif method == "GET":
                self.send_static()
            else:
                raise Refusal(404, Said.of("refuse.no-such-address"))
        except Refusal as refusal:
            self.send_json(refusal.status, refusal.body(self.tongue()))
        except Exception:
            log.exception("the request failed: %s %s", method, path)
            self.close_connection = True
            self.send_json(500, {"error": self.tongue().say("refuse.inside")})

    # --- routes ---------------------------------------------------------------------------------
    def get_map(self) -> None:
        """The snapshot as the map draws it: subnets, devices, roads, findings and notes, with the layout."""
        self.watch()
        tongue = self.tongue()
        self.send_json(200, {**self.app.view(self.asked("at"), tongue),
                             "move": self.moving().payload(tongue),
                             "layout": self.app.layout().payload(),
                             # Where the map itself lives, and what its container watcher last
                             # saw there: the stack of containers stands by that house's yard.
                             "here": self.app.here(),
                             "docker": self.app.containers().summary()})

    def get_story(self) -> None:
        """The network in words: this is where those who read rather than look arrive."""
        self.watch()
        self.send_body(200, "text/markdown; charset=utf-8",
                       self.app.story(self.asked("at"), self.tongue()).encode("utf-8"))

    def get_guide(self) -> None:
        """A signpost for a reading agent: what lies where, so the page need not be clicked."""
        self.watch()
        self.send_body(200, "text/markdown; charset=utf-8", guide(self.tongue()).encode("utf-8"))

    def get_history(self) -> None:
        """The snapshots kept on the shelf, freshest first: any of them opens with ?at=<name>."""
        self.watch()
        self.send_json(200, self.app.history())

    def get_langs(self) -> None:
        """Which languages the map can speak. The page fills its picker from this."""
        self.send_json(200, self.app.langs())

    def get_layout(self) -> None:
        """Where things stand and how big the island is, and whether this address may move them."""
        self.watch()
        self.send_json(200, {**self.app.layout().payload(),
                             "move": self.moving().payload(self.tongue())})

    def put_layout(self) -> None:
        """Keeps where things stand and how big the island is: the page sends it after every drag."""
        self.allow_write(self.moving())
        body = self.read_json()
        if not isinstance(body, dict) or "places" not in body:
            raise Refusal(400, Said.of("refuse.want-places"))
        layout = self.app.move(body["places"], body.get("looks"), body.get("field"))
        self.send_json(200, layout.payload())

    def put_device(self) -> None:
        """Names a device, picks its picture, hides it or pins it: the atlas next to the snapshot."""
        self.allow_write(self.moving())
        body = self.read_json()
        if not isinstance(body, dict) or not isinstance(body.get("device"), str) or not body["device"]:
            raise Refusal(400, Said.of("refuse.want-device"))
        fields = {key: body[key] for key in ("name", "kind", "hidden", "pinned") if key in body}
        if not fields:
            raise Refusal(400, Said.of("refuse.nothing-to-change"))
        for key in ("name", "kind"):
            if key in fields and not isinstance(fields[key], str):
                raise Refusal(400, Said.of("refuse.name-kind-strings"))
        for key in ("hidden", "pinned"):
            if key in fields and not isinstance(fields[key], bool):
                raise Refusal(400, Said.of("refuse.hidden-pinned-bool"))
        self.send_json(200, self.app.name_device(body["device"], fields))

    def put_segment(self) -> None:
        """Names a subnet or gives it a colour."""
        self.allow_write(self.moving())
        body = self.read_json()
        if not isinstance(body, dict) or not isinstance(body.get("segment"), str) or not body["segment"]:
            raise Refusal(400, Said.of("refuse.want-segment"))
        fields = {key: body[key] for key in ("title", "colour") if key in body}
        if not fields or not all(isinstance(value, str) for value in fields.values()):
            raise Refusal(400, Said.of("refuse.title-colour-strings"))
        self.send_json(200, self.app.name_segment(body["segment"], fields))

    def put_port(self) -> None:
        """Writes down what sits on a port and why it is open: {key, note}, the key as a line of
        access names the place and the port ("router udp 53", "192.168.20.10 tcp 443"). An
        empty note removes it."""
        self.allow_write(self.moving())
        body = self.read_json()
        if not isinstance(body, dict) or not isinstance(body.get("key"), str) \
                or not isinstance(body.get("note"), str):
            raise Refusal(400, Said.of("refuse.want-port"))
        self.send_json(200, self.app.note_port(body["key"], body["note"]))

    def get_houses(self) -> None:
        """Who is out there: both lists, and what each of them is naming right now."""
        self.watch()
        tongue = self.tongue()
        self.send_json(200, self.app.houses(tongue))

    def get_specs_text(self) -> None:
        """What each of the owner's machines is made of, in words: system, processor, cores,
        memory, disks — as the owner or an agent wrote it down — and how to write more."""
        self.watch()
        self.send_body(200, "text/markdown; charset=utf-8", self.app.specs_text(self.tongue()).encode("utf-8"))

    def get_specs(self) -> None:
        """Every device on the map with its card of characteristics, as JSON: what /specs.md tells in words."""
        self.watch()
        self.send_json(200, self.app.specs(self.tongue()))

    def put_specs(self) -> None:
        """Writes a device's card of characteristics: the lines sent are set, empty ones wiped,
        the rest kept.

        From the networks that may move things on the map, any device's card, and its name;
        from any other network the map is shown to, only the asking device's own card."""
        moving = self.moving()
        self.allow_write(moving if moving.allowed else self.watch())
        body = self.read_json()
        if not isinstance(body, dict) or not isinstance(body.get("device"), str) or not body["device"]:
            raise Refusal(400, Said.of("refuse.want-device"))
        name = body.get("name") if "name" in body else None
        if name is not None and not isinstance(name, str):
            raise Refusal(400, Said.of("refuse.name-kind-strings"))
        fields = {key: value for key, value in body.items() if key not in ("device", "name", "by")}
        if not fields and name is None:
            raise Refusal(400, Said.of("refuse.nothing-to-change"))
        self.send_json(200, self.app.write_card(body["device"], fields, name, body.get("by"), moving, self.tongue()))

    def get_containers_text(self) -> None:
        """What runs on the map's host, in words: the answer to "is it there already?", and the
        next free port for a new app."""
        self.watch()
        self.send_body(200, "text/markdown; charset=utf-8",
                       self.app.containers().markdown(self.tongue(), self.app.listening()).encode("utf-8"))

    def get_containers(self) -> None:
        """The containers and projects on the map's host as JSON: what /containers.md tells in words."""
        self.watch()
        self.send_json(200, self.app.containers().api(self.app.listening()))

    def get_names(self) -> None:
        """The router's own names, and who holds the address each of them leads to."""
        self.watch()
        self.send_json(200, self.app.names(self.tongue()))

    def get_settings(self) -> None:
        """Who sees the map: the networks it is shown to, and whether this address may change that."""
        self.watch()
        self.send_json(200, {**self.app.watchers(), "move": self.moving().payload(self.tongue())})

    def put_settings(self) -> None:
        """Chooses the networks the map is shown to."""
        verdict = self.moving()
        self.allow_write(verdict)
        body = self.read_json()
        if not isinstance(body, dict) or "show" not in body:
            raise Refusal(400, Said.of("refuse.want-show"))
        self.send_json(200, self.app.choose_watchers(body["show"], verdict.address or ""))

    def post_refresh(self) -> None:
        """Takes the router's snapshot and the NAS's containers anew, and answers once both are written.

        Anyone who may see the map may ask, from a script as well as from the page: it changes
        nothing but the snapshots' age. A snapshot younger than half a minute counts as fresh and
        is not taken again, and there is one walk to the router at a time — whoever asks during a
        walk waits for that walk. 503 when a snapshot could not be taken: the body says which and
        why."""
        self.watch()
        done = Refresh(self.app).run(self.tongue())
        self.send_json(200 if done["fresh"] else 503, done)

    def post_ports(self) -> None:
        """Knocks at a device's doors and answers which of them are open.

        Knocking is an act in the network, not a reading of a snapshot: asked as strictly."""
        self.allow_write(self.moving())
        body = self.read_json()
        if not isinstance(body, dict) or not isinstance(body.get("ip"), str):
            raise Refusal(400, Said.of("refuse.want-ip"))
        self.send_json(200, self.app.doors(body["ip"]))

    def health(self) -> None:
        """The commit this copy was built from, as `version`; a working copy has none, and says null."""
        self.send_json(200, {"status": "ok", "version": self.app.version})

    def get_packages(self) -> None:
        """What this copy of the map is made of — Python, its distributions and the system's
        packages, each named as osv.dev names it — with the commit, as in /healthz, as `version`.

        Open to everyone, like /healthz: names and versions, nothing about the network."""
        self.send_json(200, {"version": self.app.version, **self.app.packages.listing()})

    def get_openapi(self) -> None:
        """This description: every route the map answers, read off its own route table.

        Open to everyone, like /healthz: it holds paths and words, nothing about the network."""
        self.send_json(200, ApiSpec(type(self), self.app.web_dir, self.app.version).document())

    # --- who is allowed -------------------------------------------------------------------------
    def watch(self):
        verdict = self.app.doorman.may_see(self.client_address[0], self.headers.get("X-Forwarded-For"))
        if not verdict.allowed:
            raise Refusal(403, verdict.reason)
        return verdict

    def moving(self):
        return self.app.doorman.may_move(self.client_address[0], self.headers.get("X-Forwarded-For"))

    def allow_write(self, verdict) -> None:
        if not self.same_origin():
            raise Refusal(403, Said.of("refuse.not-from-the-map"))
        if self.headers.get_content_type() != "application/json":
            raise Refusal(415, Said.of("refuse.want-json"))
        if not verdict.allowed:
            raise Refusal(403, verdict.reason, move=verdict.payload(self.tongue()))

    def same_origin(self) -> bool:
        origin, host = self.headers.get("Origin"), self.headers.get("Host")
        if not origin or not host:
            return False
        parts = urlsplit(origin)
        return parts.scheme in ("http", "https") and parts.netloc.lower() == host.lower()

    def read_json(self):
        length = self.headers.get("Content-Length", "")
        if not length.isdigit():
            raise Refusal(411, Said.of("refuse.want-length"))
        if int(length) > self.app.BODY_MOST:
            self.close_connection = True
            raise Refusal(413, Said.of("refuse.too-big"))
        raw = self.rfile.read(int(length))
        self.body_read = True
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise Refusal(400, Said.of("refuse.body-not-json")) from error

    # --- sending --------------------------------------------------------------------------------
    def send_static(self) -> None:
        file = self.app.static_file(self.path)
        if file is None:
            self.send_body(404, "text/plain; charset=utf-8",
                           (self.tongue().say("refuse.no-such-page") + "\n").encode("utf-8"))
            return
        kind = self.app.TYPES[file.suffix.lower()]
        extra = {"Content-Security-Policy": self.CSP} if kind.startswith("text/html") else {}
        self.send_body(200, kind, file.read_bytes(), cache="no-cache", extra=extra)

    def send_json(self, status: int, payload: dict) -> None:
        self.send_body(status, "application/json; charset=utf-8",
                       json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def send_body(self, status: int, kind: str, body: bytes, cache: str = "no-store",
                  extra: dict | None = None) -> None:
        # A body nobody read would stay on a kept connection and start the next request.
        if self.body_left():
            self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if self.close_connection:
            self.send_header("Connection", "close")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def body_left(self) -> bool:
        """Whether the asker sent a body that no route read: the page's refresh sends `{}`, and
        the route needs nothing from it."""
        if getattr(self, "body_read", False):
            return False
        length = self.headers.get("Content-Length", "")
        return (length.isdigit() and int(length) > 0) or "Transfer-Encoding" in self.headers

    # --- the log --------------------------------------------------------------------------------
    def log_request(self, code="-", size="-") -> None:
        if urlsplit(self.path).path in self.QUIET:
            return
        who = self.app.doorman.address(self.client_address[0], self.headers.get("X-Forwarded-For"))
        log.info('%s "%s" %s', who or self.client_address[0], self.requestline,
                 getattr(code, "value", code))

    def log_error(self, fmt, *args) -> None:
        level = logging.DEBUG if fmt.startswith("Request timed out") else logging.WARNING
        log.log(level, "%s %s", self.client_address[0], fmt % args)

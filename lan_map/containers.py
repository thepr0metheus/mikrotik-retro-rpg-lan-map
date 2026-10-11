"""What runs on the map's own host: its containers and compose projects, told to agents.

Agents put applications on the NAS by the approved schemes, and the first question there is
"is it there already?". Not every agent may ssh to the NAS, and that is on purpose. So the map
answers over HTTP, the way it answers about the network: /containers.md and /api/containers.

Two halves share one file, data/containers.json, and this module is the one place that says
what is in it:

- The watcher asks Docker, over its socket, which containers there are, and lists the folders
  beside the map's own that hold a compose file. It is a service of its own in the map's
  compose project, so it runs on whatever host the map runs on. It has no network at all, and
  the map's web side never touches Docker.
- The map reads the file and tells it: by project, what is present but not running, and when
  the snapshot was taken. A watcher on a schedule whose snapshot is three intervals old is
  called stale, not passed off as live; one that answers only when asked is as fresh as the
  last question, and the time at the top says when that was.

The same round reads DSM's own gate on the host — its reverse proxy and firewall — into the same
file, under "gate". What that part holds is said in lan_map/gate.py, not here.

Nothing secret leaves Docker. Only the fields named in `Watcher.container` are copied: never
the environment, the command line, the mounts, or any label but compose's three and the home's
own `arpa.home.lan.name` — the name an app is served by, which ties a container in the host's
network to its port behind DSM's proxy.

`python -m lan_map.containers` runs the watcher: a snapshot at its start, then one each time the
map leaves a note, data/containers.ask — that is how a reader's POST /api/refresh reaches a
service with no network. `--every 3600` adds a round on a schedule; `--once` takes one snapshot.
"""
from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import logging
import os
import re
import signal
import socket
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, ClassVar

from .gate import Door, GateReader
from .listening import UNASKED, FreePort, Listening
from .scribe import cell
from .snapshot import utc_now
from .tongue import Tongue

log = logging.getLogger("lan_map.containers")


class DockerError(RuntimeError):
    """Docker did not answer, or answered with an error."""


def docker_time(text) -> datetime | None:
    """A moment as Docker writes it — "2026-09-27T11:10:37.123456789Z", nanoseconds and a Z —
    which Python's own parser takes only in part. None when there is no moment."""
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)?", text or "")
    if not match:
        return None
    fraction = (match.group(2) or "").ljust(6, "0")[:6]
    zone = "+00:00" if match.group(3) in (None, "Z") else match.group(3)
    return datetime.fromisoformat(f"{match.group(1)}.{fraction}{zone}")


class _UnixConnection(http.client.HTTPConnection):
    """HTTP over a unix socket: how Docker's own API is reached."""

    def __init__(self, path: str, timeout: float):
        super().__init__("docker", timeout=timeout)
        self.socket_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


@dataclass(frozen=True)
class DockerApi:
    """Docker's API over its socket: GET and JSON, nothing else is ever asked."""

    path: str = "/var/run/docker.sock"
    timeout: float = 20

    def get(self, what: str):
        link = _UnixConnection(self.path, self.timeout)
        try:
            link.request("GET", what)
            answer = link.getresponse()
            body = answer.read()
        except OSError as error:
            raise DockerError(f"{what}: {error}") from error
        finally:
            link.close()
        if answer.status != 200:
            raise DockerError(f"{what}: {answer.status} {body[:200].decode('utf-8', 'replace')}")
        return json.loads(body)


@dataclass
class Watcher:
    """Takes one snapshot of the host's containers and writes it, whole, where the map reads it."""

    #: Anything with get(path) → JSON: DockerApi on the host, a stand-in in tests.
    api: object
    #: The folder that holds the map's own folder and its neighbours, as mounted here.
    apps: Path
    #: How often a snapshot is taken, in seconds: the map judges freshness by it.
    every: int = 0
    #: This container's hostname — its id, by Docker's default — to find the map's own folder.
    myself: str = field(default_factory=socket.gethostname)
    clock: Callable[[], datetime] = utc_now
    #: DSM's gate on the same host, read in the same round. None: this watcher does not read it.
    gate: GateReader | None = None

    PROJECT: ClassVar[str] = "com.docker.compose.project"
    SERVICE: ClassVar[str] = "com.docker.compose.service"
    FOLDER: ClassVar[str] = "com.docker.compose.project.working_dir"
    COMPOSE: ClassVar[tuple] = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")
    #: Docker's word for "never": a container that was created but not started.
    NEVER: ClassVar[str] = "0001-01-01T00:00:00Z"
    #: The one label of the home's own: the name DSM's reverse proxy serves the app by. Every
    #: app on the NAS is asked to carry it.
    SERVED: ClassVar[str] = "arpa.home.lan.name"
    #: What such a name may look like. Anything else in the label stays inside Docker.
    HOSTNAME: ClassVar = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")
    #: The note the map leaves beside the snapshot when a reader wants it fresh: see refresh.py.
    ASK: ClassVar[str] = "containers.ask"
    #: How often the watcher looks for that note while it rests, in seconds.
    STEP: ClassVar[int] = 2

    def snapshot(self) -> dict:
        info = self.api.get("/info")
        listed = self.api.get("/containers/json?all=1")
        containers = [self.container(one, self.api.get(f"/containers/{one['Id']}/json"))
                      for one in listed]
        snapshot = {
            "taken": self.clock().astimezone(timezone.utc).isoformat(timespec="seconds"),
            "every": self.every,
            # One line each: DSM says its OperatingSystem across two ("Synology NAS\n (containerized)").
            "host": {key: " ".join(str(info.get(field) or "").split())
                     for key, field in (("name", "Name"), ("os", "OperatingSystem"), ("docker", "ServerVersion"))},
            "apps": self.home(listed),
            "folders": self.folders(),
            "containers": sorted(containers, key=lambda one: (one["project"], one["service"], one["name"])),
        }
        if self.gate is not None:
            snapshot["gate"] = self.gate.read()
        return snapshot

    def container(self, listed: dict, inspected: dict) -> dict:
        """One container: these fields and no others. Everything else stays inside Docker."""
        labels = listed.get("Labels") or {}
        state = inspected.get("State") or {}
        return {
            "name": ((listed.get("Names") or ["?"])[0]).lstrip("/"),
            "project": labels.get(self.PROJECT, ""),
            "service": labels.get(self.SERVICE, ""),
            "folder": labels.get(self.FOLDER, ""),
            "image": listed.get("Image", ""),
            "state": listed.get("State", ""),
            "health": (state.get("Health") or {}).get("Status", ""),
            "started": self.when(state.get("StartedAt")),
            "finished": self.when(state.get("FinishedAt")),
            "exit_code": state.get("ExitCode"),
            "restarts": inspected.get("RestartCount", 0),
            "network": (listed.get("HostConfig") or {}).get("NetworkMode", ""),
            "ports": self.ports(listed.get("Ports") or []),
            "host_ports": self.host_ports(listed.get("Ports") or []),
            "served": self.served(labels),
        }

    def served(self, labels: dict) -> str:
        """The name the app says DSM's proxy serves it by, from its compose label — only when it
        reads as a host name. "" when there is no such label."""
        name = str(labels.get(self.SERVED, "")).strip().lower()
        return name if len(name) <= 253 and self.HOSTNAME.fullmatch(name) else ""

    def when(self, text) -> str:
        return "" if not text or text.startswith(self.NEVER) else text

    @staticmethod
    def published(ports: list) -> list:
        """Docker's entries for the ports published on the host. A port exposed inside only has
        no public side: nobody outside reaches it."""
        return [port for port in ports if port.get("PublicPort")]

    @staticmethod
    def host_ports(ports: list) -> list:
        """The host's side of the published ports, once each: the numbers a new app must not take."""
        return sorted({port["PublicPort"] for port in Watcher.published(ports)})

    @staticmethod
    def ports(ports: list) -> list:
        """The published ports, once each: Docker lists one port twice, for IPv4 and for IPv6."""
        seen, found = set(), []
        for port in Watcher.published(ports):
            key = (port["PublicPort"], port.get("PrivatePort"), port.get("Type", "tcp"))
            if key in seen:
                continue
            seen.add(key)
            ip = port.get("IP", "")
            where = "" if ip in ("", "0.0.0.0", "::") else f"{ip}:"
            found.append(f"{where}{key[0]}→{key[1]}/{key[2]}")
        return found

    def home(self, listed: list) -> str:
        """Where the map's folder and its neighbours live on the host: found through this very
        container's own compose labels. "" when this watcher does not run from compose."""
        for one in listed:
            if one.get("Id", "").startswith(self.myself or "-"):
                folder = (one.get("Labels") or {}).get(self.FOLDER, "")
                return str(Path(folder).parent) if folder else ""
        return ""

    def folders(self) -> list:
        """The folders beside the map's that hold a compose file: projects, started or not.
        Only names are read here; no compose file is ever opened."""
        found = []
        if not self.apps.is_dir():
            return found
        for folder in sorted(self.apps.iterdir(), key=lambda path: path.name.lower()):
            if folder.name.startswith(("#", ".", "@")) or not folder.is_dir():
                continue
            compose = next((name for name in self.COMPOSE if (folder / name).is_file()), "")
            if compose:
                found.append({"folder": folder.name, "compose": compose})
        return found

    @staticmethod
    def write(snapshot: dict, path: Path) -> None:
        """Whole or not at all: a temporary file, renamed. 644, so the map can read it."""
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=".containers-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(snapshot, out, ensure_ascii=False, indent=1)
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def run(self, out: Path, once: bool = False, sleep: Callable[[float], None] = time.sleep) -> None:
        """Once an hour, for as long as the service runs, and at once when the map asks. A
        failed round leaves the last snapshot where it is: the map will call it stale when it
        grows old.

        The map's note is taken away before the round, not after: a note left while the round
        is under way asks for the next one, and the map waits for a snapshot taken after it."""
        ask = out.parent / self.ASK
        while True:
            with contextlib.suppress(FileNotFoundError):
                ask.unlink()
            try:
                self.write(self.snapshot(), out)
                log.info("snapshot written: %s", out)
            except (DockerError, OSError, ValueError) as error:
                log.warning("no snapshot this round: %s", error)
                if once:
                    raise
            if once:
                return
            self.rest(ask, sleep)

    def rest(self, ask: Path, sleep: Callable[[float], None]) -> None:
        """Until the next round: until the map leaves a note asking for one, and on a schedule
        no longer than `every` seconds. Zero is no schedule: only the note wakes the watcher."""
        waited = 0
        while not ask.exists():
            if self.every and waited >= self.every:
                return
            sleep(self.STEP)
            waited += self.STEP


# --- the map's side ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Containers:
    """The last snapshot as the map tells it. `payload` is None when there is none yet."""

    payload: dict | None
    now: datetime
    #: Why there is nothing to tell, when there is nothing: no file, or a file that does not read.
    missing: str = ""

    #: A snapshot this many intervals old is stale: the watcher is not running.
    STALE: ClassVar[int] = 3

    @classmethod
    def read(cls, path: Path, now: datetime) -> "Containers":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(None, now, "containers.none")
        except (OSError, ValueError) as error:
            log.warning("containers.json does not read: %s", error)
            return cls(None, now, "containers.unreadable")
        return cls(payload, now)

    @property
    def age(self) -> timedelta | None:
        taken = docker_time((self.payload or {}).get("taken"))
        return self.now - taken if taken else None

    @property
    def every(self) -> int:
        """The watcher's schedule in seconds; 0 when it snapshots only when asked. A snapshot
        older than the field was taken hourly."""
        every = (self.payload or {}).get("every")
        return 3600 if every is None else every

    @property
    def stale(self) -> bool:
        """Too old to be the present: three intervals of a watcher on a schedule. A watcher that
        answers only when asked is never stale — its snapshot is as old as the last question.
        A snapshot with no readable time is stale either way."""
        if self.payload is None:
            return False
        age = self.age
        return age is None or (self.every > 0 and age > timedelta(seconds=self.every * self.STALE))

    def projects(self) -> list:
        """Every compose project: its folder, its containers, and how many of them run.

        A folder with a compose file but no containers is a project too — present, never
        started. A container is matched to a folder by compose's own label, or by project name
        when the label is missing."""
        payload = self.payload or {}
        apps = payload.get("apps", "")
        containers = payload.get("containers", [])
        found = {}
        for one in payload.get("folders", []):
            found[one["folder"]] = {"project": one["folder"], "folder": f"{apps}/{one['folder']}" if apps else one["folder"],
                                    "compose": one["compose"], "containers": []}
        for container in containers:
            if not container.get("project"):
                continue
            key = Path(container["folder"]).name if container.get("folder") else container["project"]
            entry = found.setdefault(key, {"project": container["project"], "folder": container.get("folder", ""),
                                           "compose": "", "containers": []})
            entry["project"] = container["project"]
            entry["containers"].append(container)
        for entry in found.values():
            running = sum(1 for one in entry["containers"] if one.get("state") == "running")
            entry["running"] = running
            entry["state"] = ("not-started" if not entry["containers"] else "running" if running == len(entry["containers"])
                              else "partly" if running else "stopped")
        return sorted(found.values(), key=lambda entry: entry["project"].lower())

    def loose(self) -> list:
        """Containers started without compose: they belong to no project."""
        return [one for one in (self.payload or {}).get("containers", []) if not one.get("project")]

    def summary(self) -> dict:
        """What the stack of containers by the host's yard says: counts, not the list."""
        if self.payload is None:
            return {"missing": self.missing, "host": "", "running": 0, "idle": 0,
                    "unhealthy": 0, "stale": False, "taken": ""}
        containers = self.payload.get("containers", [])
        return {"missing": "", "host": (self.payload.get("host") or {}).get("name", ""),
                "running": sum(1 for one in containers if one.get("state") == "running"),
                "idle": sum(1 for entry in self.projects() if entry["state"] in ("stopped", "not-started")),
                "unhealthy": sum(1 for one in containers if one.get("health") == "unhealthy"),
                "stale": self.stale, "taken": self.payload.get("taken", "")}

    def doors(self) -> list:
        """The names DSM's reverse proxy serves, as the watcher read them beside the containers."""
        return [Door.of(door) for door in ((self.payload or {}).get("gate") or {}).get("doors") or []]

    def proxied(self) -> list:
        """«Port → name → where it leads»: every port behind DSM's proxy, by port. A port here is
        taken, though Docker may know nothing of it."""
        rows = [{"port": door.backend[1], "name": door.name, "host": door.backend[0],
                 "nas": door.local("")} for door in self.doors()]
        return sorted(rows, key=lambda row: (row["port"], row["name"]))

    @staticmethod
    def proxy_for(container: dict, doors: list):
        """The proxy's door a container is served through: the one its label names, in any network.
        With no label, only in the host's network: the one whose name starts with its project's,
        since an app has one name for everything. In Docker's own network a project is often many
        containers, and its name would fit them all. A label naming no door finds none: no guess
        in its place."""
        if container.get("served"):
            return next((door for door in doors if door.name == container["served"]), None)
        if container.get("network") != "host":
            return None
        project = container.get("project")
        return next((door for door in doors if project and door.name.split(".")[0] == project), None)

    def host_ports(self) -> set | None:
        """Every port Docker publishes on the host, by the snapshot. None when the snapshot is
        older than this field and does not say."""
        containers = (self.payload or {}).get("containers", [])
        if any("host_ports" not in one for one in containers):
            return None
        return {port for one in containers for port in one["host_ports"]}

    def free_port(self, listening: Listening = UNASKED) -> dict:
        """The port a new app takes next: none behind the proxy, none Docker publishes and, when
        the host's tables read, none the host listens on. With no reading of the proxy there is
        no answer: a port behind it is taken even while its app is stopped and nothing listens."""
        span = FreePort.span()
        if self.payload is None:
            return {"port": None, **span, "listening": None, "missing": self.missing}
        gate = self.payload.get("gate") or {"missing": "gate.not-read"}
        published = self.host_ports()
        why = gate.get("missing") or ("free-port.old-snapshot" if published is None else "")
        if why:
            return {"port": None, **span, "listening": None, "missing": why}
        taken = {row["port"] for row in self.proxied()} | published
        known = listening.ports is not None
        if known:
            taken |= listening.ports
        port = FreePort.first(taken)
        if port is None:
            return {"port": None, **span, "listening": known, "missing": "free-port.none-left"}
        return {"port": port, **span, "listening": known, "missing": listening.missing}

    def api(self, listening: Listening = UNASKED) -> dict:
        if self.payload is None:
            return {"missing": self.missing, "taken": "", "stale": False, "projects": [], "loose": [],
                    "proxied": [], "free_port": self.free_port(listening)}
        age, doors = self.age, self.doors()

        def told(one: dict) -> dict:
            door = self.proxy_for(one, doors)
            return {**one, "proxy": {"name": door.name, "port": door.backend[1]} if door else None}

        return {"missing": "", "taken": self.payload.get("taken", ""), "every": self.every,
                "age_seconds": int(age.total_seconds()) if age is not None else None, "stale": self.stale,
                "host": self.payload.get("host", {}), "apps": self.payload.get("apps", ""),
                "projects": [{**entry, "containers": [told(one) for one in entry["containers"]]}
                             for entry in self.projects()],
                "loose": [told(one) for one in self.loose()], "proxied": self.proxied(),
                "free_port": self.free_port(listening)}

    def markdown(self, tongue: Tongue, listening: Listening = UNASKED) -> str:
        return ContainersText(self, tongue, listening).markdown()


@dataclass(frozen=True)
class ContainersText:
    """The snapshot in words, for an agent: projects first, then what is present but idle."""

    containers: Containers
    tongue: Tongue
    #: What listens on the host right now: it decides, with the proxy and Docker, the free port.
    listening: Listening = UNASKED

    def say(self, key: str, **parts) -> str:
        return self.tongue.say(key, **parts)

    def markdown(self) -> str:
        known = self.containers
        if known.payload is None:
            lines = ["# " + self.say("containers.title-unknown"), "", self.say(known.missing), ""]
        else:
            lines = [*self.head(), *self.live(), *self.idle(), *self.outside(), *self.behind(), *self.free(),
                     *self.notes()]
        return "\n".join(lines).rstrip() + "\n"

    def head(self) -> list:
        payload = self.containers.payload
        host = payload.get("host", {})
        every = self.containers.every
        taken = (self.say("containers.taken", taken=payload.get("taken", "?"), minutes=every // 60,
                          docker=host.get("docker") or "?", os=host.get("os") or "?") if every
                 else self.say("containers.taken-asked", taken=payload.get("taken", "?"),
                               docker=host.get("docker") or "?", os=host.get("os") or "?"))
        lines = ["# " + self.say("containers.title", host=host.get("name") or "?"), "", taken, ""]
        if self.containers.stale:
            age = self.containers.age
            lines += ["**" + self.say("containers.stale", age=self.span(age) if age else "?") + "**", ""]
        return lines

    def live(self) -> list:
        """The projects with something running. Stopped ones are told apart, in idle()."""
        rows = []
        for entry in self.containers.projects():
            if entry["state"] not in ("running", "partly"):
                continue
            for one in entry["containers"]:
                rows.append([entry["project"], one["service"] or "—", one["name"], one["image"],
                             self.state(one), self.health(one), self.up(one), self.ports(one)])
        if not rows:
            return []
        return ["## " + self.say("containers.projects"), "",
                *self.table([self.say(f"containers.col.{key}") for key in
                             ("project", "service", "container", "image", "state", "health", "up", "ports")], rows)]

    def idle(self) -> list:
        idle = [entry for entry in self.containers.projects() if entry["state"] in ("stopped", "not-started")]
        rows = [[entry["project"], entry["folder"], entry["compose"] or "—",
                 self.say(f"containers.idle.{entry['state']}")] for entry in idle]
        if not rows:
            return []
        return ["## " + self.say("containers.idle"), "", self.say("containers.idle.hint"), "",
                *self.table([self.say(f"containers.col.{key}") for key in ("project", "folder", "compose", "what")], rows)]

    def outside(self) -> list:
        rows = [[one["name"], one["image"], self.state(one), self.health(one), self.up(one), self.ports(one)]
                for one in self.containers.loose()]
        if not rows:
            return []
        return ["## " + self.say("containers.loose"), "",
                *self.table([self.say(f"containers.col.{key}") for key in
                             ("container", "image", "state", "health", "up", "ports")], rows)]

    def behind(self) -> list:
        """The ports behind DSM's reverse proxy: the ports of apps in the host's network that
        Docker cannot know, and which ones a new app must not take."""
        gate = self.containers.payload.get("gate") or {}
        if gate.get("missing"):
            return ["## " + self.say("containers.proxy"), "", self.say(gate["missing"]), ""]
        rows = [[row["port"], row["name"],
                 self.say("containers.proxy.nas") if row["nas"] else self.say("containers.proxy.machine", host=row["host"])]
                for row in self.containers.proxied()]
        if not rows:
            return []
        return ["## " + self.say("containers.proxy"), "", self.say("containers.proxy.intro"), "",
                *self.table([self.say(f"containers.col.{key}") for key in ("port", "address", "leads")], rows)]

    def free(self) -> list:
        """The port a new app takes next, or why the map names none."""
        answer = self.containers.free_port(self.listening)
        span = {key: answer[key] for key in ("first", "last", "step")}
        if answer["port"] is None:
            said = (self.say("free-port.none-left", **span) if answer["missing"] == "free-port.none-left"
                    else self.say("free-port.unknown", why=self.say(answer["missing"])))
        elif answer["listening"]:
            said = self.say("free-port.free", port=answer["port"], **span)
        else:
            said = self.say("free-port.unchecked", port=answer["port"], why=self.say(answer["missing"]))
        return ["## " + self.say("free-port"), "", said, ""]

    def notes(self) -> list:
        return ["## " + self.say("containers.about"), "",
                "- " + self.say("containers.about.json"),
                "- " + self.say("containers.about.secrets"),
                "- " + self.say("containers.about.ports"),
                "- " + self.say("containers.about.fresh"), ""]

    # --- one cell at a time --------------------------------------------------------------------
    def state(self, one: dict) -> str:
        state = one.get("state") or "?"
        said = self.say(f"containers.state.{state}") if self.tongue.has(f"containers.state.{state}") else state
        if state == "exited" and one.get("exit_code") is not None:
            said += f" ({one['exit_code']})"
        return said

    def health(self, one: dict) -> str:
        health = one.get("health")
        if not health:
            return "—"
        return self.say(f"containers.health.{health}") if self.tongue.has(f"containers.health.{health}") else health

    def up(self, one: dict) -> str:
        """How long it has been running, as of the snapshot — not as of reading."""
        taken = docker_time(self.containers.payload.get("taken"))
        started = docker_time(one.get("started"))
        if one.get("state") != "running" or not taken or not started:
            return "—"
        return self.span(taken - started)

    def ports(self, one: dict) -> str:
        """The ports Docker publishes, or «host network», whose ports Docker does not know; then the
        port behind DSM's proxy, when the container is served through it."""
        where = (self.say("containers.host-network") if one.get("network") == "host"
                 else ", ".join(one.get("ports") or []))
        door = self.containers.proxy_for(one, self.containers.doors())
        proxied = self.say("containers.proxied", port=door.backend[1], name=door.name) if door else ""
        return "; ".join(part for part in (where, proxied) if part) or "—"

    def span(self, delta: timedelta) -> str:
        """Two largest parts, in the map's own units: "3d 4h", "2h 15m"."""
        seconds = max(0, int(delta.total_seconds()))
        parts = []
        for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
            if seconds >= size or (unit == "m" and not parts):
                parts.append(self.say(f"span.unit.{unit}", number=seconds // size))
                seconds %= size
        return " ".join(parts[:2])

    @staticmethod
    def table(head: list, rows: list) -> list:
        lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
        return lines + ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows] + [""]


def main(argv: list | None = None) -> int:
    """The watcher's way in: the real socket, the real clock, the folders beside the map."""
    parser = argparse.ArgumentParser(prog="python -m lan_map.containers")
    parser.add_argument("--socket", default="/var/run/docker.sock")
    parser.add_argument("--apps", default="/apps", help="the folder beside the map's, as mounted")
    parser.add_argument("--out", default="/app/data/containers.json")
    parser.add_argument("--every", type=int, default=0,
                        help="seconds between snapshots; 0, the default: only at the start and when the map asks")
    parser.add_argument("--once", action="store_true", help="one snapshot, then exit")
    parser.add_argument("--nginx", default="/usr/local/etc/nginx", help="DSM's nginx folder, as mounted")
    parser.add_argument("--firewall", default="/usr/syno/etc/firewall.d", help="DSM's firewall folder, as mounted")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # The watcher is PID 1 of its container, and PID 1 has no default for SIGTERM: without
    # this, `docker compose stop` waits ten seconds and kills it. Nothing is lost by leaving at
    # once — every snapshot is written whole or not at all.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    watcher = Watcher(DockerApi(args.socket), Path(args.apps), every=max(60, args.every) if args.every > 0 else 0,
                      gate=GateReader(Path(args.nginx), Path(args.firewall)))
    try:
        watcher.run(Path(args.out), once=args.once)
    except (DockerError, OSError, ValueError) as error:
        print(f"no snapshot: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

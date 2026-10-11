import json
import stat
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from lan_map.containers import Containers, DockerError, Watcher, docker_time
from lan_map.gate import GateReader
from lan_map.listening import Listening
from lan_map.tongue import Tongue

TAKEN = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
MAP_ID = "a1b2c3d4e5f6" + "0" * 52
SECRET = "hunter2-do-not-leak"


def listed(cid, name, image, state, project="", service="", folder="", network="bridge", ports=(), served=""):
    """A row of GET /containers/json, with the fields that must never leave Docker in it too."""
    labels = {"maintainer": SECRET, "com.docker.compose.config-hash": SECRET}
    if served:
        labels["arpa.home.lan.name"] = served
    if project:
        labels.update({"com.docker.compose.project": project, "com.docker.compose.service": service,
                       "com.docker.compose.project.working_dir": folder})
    return {"Id": cid, "Names": [f"/{name}"], "Image": image, "State": state,
            "Status": "Up 2 hours", "Command": f"run --token {SECRET}", "Labels": labels,
            "Ports": list(ports), "HostConfig": {"NetworkMode": network},
            "Mounts": [{"Source": f"/volume1/{SECRET}"}]}


def inspected(started="2026-09-28T09:30:00.123456789Z", health="", exit_code=0, restarts=0):
    state = {"StartedAt": started, "FinishedAt": "0001-01-01T00:00:00Z", "ExitCode": exit_code}
    if health:
        state["Health"] = {"Status": health, "Log": [{"Output": SECRET}]}
    return {"State": state, "RestartCount": restarts,
            "Config": {"Env": [f"TOKEN={SECRET}"], "Cmd": ["serve", SECRET]}}


class Enough(Exception):
    """Stops the watcher's endless loop from a test."""


class FakeDocker:
    """Docker's API as the watcher sees it: paths in, JSON out."""

    def __init__(self, containers: list, details: dict, fail: bool = False):
        self.containers, self.details, self.fail = containers, details, fail

    def get(self, path):
        if self.fail:
            raise DockerError("socket refused")
        if path == "/info":
            return {"Name": "NAS01", "OperatingSystem": "Synology DSM\n (containerized)", "ServerVersion": "24.0.2",
                    "Labels": [SECRET]}
        if path == "/containers/json?all=1":
            return self.containers
        return self.details[path.split("/")[2]]


def docker() -> FakeDocker:
    rows = [
        listed(MAP_ID, "lan-map", "lan-map:latest", "running", "lan-map", "lan-map",
               "/volume1/docker/lan-map", network="host", served="map.lan.example"),
        listed("b" * 64, "plane-web", "makeplane/plane-frontend:v0.24.1", "running", "plane", "web",
               "/volume1/docker/plane", ports=[
                   {"IP": "0.0.0.0", "PrivatePort": 3000, "PublicPort": 8810, "Type": "tcp"},
                   {"IP": "::", "PrivatePort": 3000, "PublicPort": 8810, "Type": "tcp"},
                   {"PrivatePort": 9000, "Type": "tcp"}]),
        listed("c" * 64, "plane-worker", "makeplane/plane-backend:v0.24.1", "exited", "plane", "worker",
               "/volume1/docker/plane"),
        listed("d" * 64, "old-chat", "mattermost/mattermost:9.1", "exited", "chat", "app",
               "/volume1/docker/chat"),
        listed("e" * 64, "stray", "alpine:3.20", "running"),
    ]
    details = {MAP_ID: inspected(health="healthy"), "b" * 64: inspected(health="starting"),
               "c" * 64: inspected(exit_code=137, restarts=3), "d" * 64: inspected(exit_code=0),
               "e" * 64: inspected()}
    return FakeDocker(rows, details)


class WatcherTest(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.apps = Path(self.folder.name) / "apps"
        for name, compose in (("lan-map", "compose.yaml"), ("plane", "docker-compose.yml"),
                              ("chat", "compose.yml"), ("xwiki", "compose.yaml")):
            (self.apps / name).mkdir(parents=True)
            (self.apps / name / compose).write_text(f"secret: {SECRET}\n", encoding="utf-8")
        (self.apps / "notes").mkdir()                       # no compose file: not a project
        (self.apps / "#recycle" / "old").mkdir(parents=True)
        (self.apps / "#recycle" / "old" / "compose.yaml").write_text("x", encoding="utf-8")
        self.watcher = Watcher(docker(), self.apps, myself=MAP_ID[:12], clock=lambda: TAKEN)
        self.snapshot = self.watcher.snapshot()

    def test_nothing_secret_leaves_docker(self):
        """Environment, command lines, mounts, other labels, health logs, compose files: none."""
        self.assertNotIn(SECRET, json.dumps(self.snapshot))

    def test_a_container_is_told_by_its_own_fields(self):
        web = next(one for one in self.snapshot["containers"] if one["name"] == "plane-web")
        self.assertEqual((web["project"], web["service"], web["image"], web["state"], web["health"]),
                         ("plane", "web", "makeplane/plane-frontend:v0.24.1", "running", "starting"))
        self.assertEqual(web["ports"], ["8810→3000/tcp"], "published once, the unpublished one not at all")
        self.assertEqual(web["host_ports"], [8810], "the host's side, once")
        self.assertEqual(web["finished"], "", "Docker's year one means never")

    def test_the_folders_beside_the_maps_are_found_by_the_watchers_own_labels(self):
        self.assertEqual(self.snapshot["apps"], "/volume1/docker")
        self.assertEqual([one["folder"] for one in self.snapshot["folders"]],
                         ["chat", "lan-map", "plane", "xwiki"])
        self.assertEqual(self.snapshot["host"],
                         {"name": "NAS01", "os": "Synology DSM (containerized)", "docker": "24.0.2"},
                         "one line each: DSM breaks its own OperatingSystem in two")

    def test_the_one_label_of_the_homes_own_is_copied_only_when_it_reads_as_a_name(self):
        served = {one["name"]: one["served"] for one in self.snapshot["containers"]}
        self.assertEqual((served["lan-map"], served["plane-web"]), ("map.lan.example", ""))
        self.assertEqual(self.watcher.served({"arpa.home.lan.name": f"x; {SECRET}"}), "")
        self.assertEqual(self.watcher.served({"arpa.home.lan.name": " Vault.LAN.example "}), "vault.lan.example")

    def test_the_same_round_reads_dsms_gate_when_told_where_it_is(self):
        """What the gate part holds is tested in test_gate; here, that the round carries it."""
        self.assertNotIn("gate", self.snapshot)
        gone = Path(self.folder.name) / "not-mounted"
        reading = Watcher(docker(), self.apps, myself=MAP_ID[:12], clock=lambda: TAKEN,
                          gate=GateReader(gone / "nginx", gone / "firewall.d")).snapshot()["gate"]
        self.assertEqual(reading["missing"], "gate.not-mounted")

    def test_the_file_is_written_whole_and_readable_by_the_map(self):
        out = Path(self.folder.name) / "data" / "containers.json"
        self.watcher.write(self.snapshot, out)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8")), self.snapshot)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o644)
        self.assertEqual([path.name for path in out.parent.iterdir()], ["containers.json"])

    def test_a_round_that_fails_leaves_the_last_snapshot_alone(self):
        out = Path(self.folder.name) / "containers.json"
        self.watcher.write(self.snapshot, out)
        before = out.read_text(encoding="utf-8")
        broken = Watcher(FakeDocker([], {}, fail=True), self.apps, clock=lambda: TAKEN)
        rounds = []

        def sleep(seconds):
            rounds.append(seconds)
            raise Enough     # one round is all this test needs

        with self.assertRaises(Enough):
            broken.run(out, sleep=sleep)
        self.assertEqual((out.read_text(encoding="utf-8"), rounds), (before, [Watcher.STEP]))
        with self.assertRaises(DockerError):
            broken.run(out, once=True)

    def test_with_no_schedule_only_a_note_wakes_the_watcher_and_on_one_the_hour_does_too(self):
        """Zero is no schedule: the watcher naps until the note, however long. On a schedule it
        naps no longer than its interval."""
        ask = Path(self.folder.name) / Watcher.ASK
        naps = []

        def sleep(seconds):
            naps.append(seconds)
            if len(naps) == 1000:
                ask.write_text("asked", encoding="utf-8")

        Watcher(docker(), self.apps, every=0).rest(ask, sleep)
        self.assertEqual(len(naps), 1000, "a thousand naps, and only the note ended them")
        ask.unlink()
        naps.clear()
        Watcher(docker(), self.apps, every=3 * Watcher.STEP).rest(ask, sleep)
        self.assertEqual(len(naps), 3, "on a schedule: three naps make the interval")

    def test_a_note_from_the_map_wakes_the_watcher_long_before_the_hour(self):
        """The watcher rests in short naps and looks for the map's note between them; the note is
        taken away before the round that answers it."""
        out = Path(self.folder.name) / "data" / "containers.json"
        note = out.parent / Watcher.ASK
        naps = []

        def sleep(seconds):
            naps.append(seconds)
            if len(naps) == 3:
                note.write_text("2026-09-28T09:30:00+00:00", encoding="utf-8")
            if len(naps) == 4:
                raise Enough

        out.parent.mkdir()
        with self.assertRaises(Enough):
            self.watcher.run(out, sleep=sleep)
        self.assertEqual(naps, [Watcher.STEP] * 4, "three naps, the note, a second round, a nap")
        self.assertFalse(note.exists())

    def test_docker_time_takes_nanoseconds_and_a_z(self):
        self.assertEqual(docker_time("2026-09-28T09:30:00.123456789Z"),
                         datetime(2026, 9, 28, 9, 30, 0, 123456, tzinfo=timezone.utc))
        self.assertIsNone(docker_time(""))
        self.assertIsNone(docker_time("yesterday"))


class ContainersTest(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        apps = Path(folder.name)
        for name in ("lan-map", "plane", "chat", "xwiki"):
            (apps / name).mkdir()
            (apps / name / "compose.yaml").write_text("x", encoding="utf-8")
        self.snapshot = Watcher(docker(), apps, myself=MAP_ID[:12], clock=lambda: TAKEN).snapshot()

    def told(self, now=TAKEN + timedelta(minutes=5), snapshot=None) -> Containers:
        return Containers(snapshot if snapshot is not None else self.snapshot, now)

    def test_projects_are_told_by_how_much_of_them_runs(self):
        states = {entry["project"]: entry["state"] for entry in self.told().projects()}
        self.assertEqual(states, {"chat": "stopped", "lan-map": "running", "plane": "partly",
                                  "xwiki": "not-started"})

    def test_a_container_without_compose_is_told_apart(self):
        self.assertEqual([one["name"] for one in self.told().loose()], ["stray"])

    def test_three_intervals_old_is_stale_and_says_so(self):
        """For a watcher on a schedule: three rounds missed mean it is not running."""
        hourly = {**self.snapshot, "every": 3600}
        fresh, old = self.told(snapshot=hourly), self.told(now=TAKEN + timedelta(hours=3, minutes=1), snapshot=hourly)
        self.assertEqual((fresh.stale, old.stale), (False, True))
        self.assertIn("Stale: this snapshot is 3h 1m old", old.markdown(Tongue.of("en")))
        self.assertNotIn("Stale", fresh.markdown(Tongue.of("en")))
        self.assertIn("taken every 60 min", fresh.markdown(Tongue.of("en")))

    def test_a_watcher_that_answers_only_when_asked_is_never_stale(self):
        """No schedule, no rounds to miss: a day-old snapshot is as old as the last question, and
        the time at the top says when that was. A snapshot from before the field was hourly."""
        self.assertEqual(self.snapshot["every"], 0)
        old = self.told(now=TAKEN + timedelta(days=1))
        self.assertFalse(old.stale)
        text = old.markdown(Tongue.of("ru"))
        self.assertIn("Снимок 2026-09-28T12:00:00+00:00. Его снимает сторож контейнеров карты по запросу: при своём"
                      " запуске и по `POST /api/refresh`.", text)
        self.assertNotIn("Устарело", text)
        older = {key: value for key, value in self.snapshot.items() if key != "every"}
        self.assertTrue(self.told(now=TAKEN + timedelta(days=1), snapshot=older).stale)

    def test_a_snapshot_without_a_readable_time_is_stale(self):
        self.assertTrue(self.told(snapshot={**self.snapshot, "taken": "soon"}).stale)

    def test_no_file_is_no_snapshot_not_an_empty_host(self):
        with TemporaryDirectory() as empty:
            told = Containers.read(Path(empty) / "containers.json", TAKEN)
        self.assertEqual(told.api()["missing"], "containers.none")
        self.assertIn("No snapshot yet", told.markdown(Tongue.of("en")))

    def test_the_text_answers_is_it_there_already(self):
        text = self.told().markdown(Tongue.of("en"))
        self.assertIn("# What runs on NAS01", text)
        self.assertIn("| plane | web | plane-web | makeplane/plane-frontend:v0.24.1 | running | starting | 2h 29m | 8810→3000/tcp |", text)
        self.assertIn("| lan-map | lan-map | lan-map | lan-map:latest | running | healthy | 2h 29m | host network |", text)
        self.assertIn("| plane | worker | plane-worker | makeplane/plane-backend:v0.24.1 | exited (137) |", text)
        self.assertIn("| xwiki | /volume1/docker/xwiki | compose.yaml | no containers |", text)
        self.assertIn("| chat | /volume1/docker/chat | compose.yaml | stopped |", text)
        self.assertNotIn(SECRET, text)

    def with_proxy(self) -> Containers:
        """Two apps in the host's network beside the map: one named like its proxy name, one whose
        label names a door the proxy does not have; Forgejo in Docker's own network, with a label;
        plane, named like its door but with no label; and a name led on to another machine."""
        host = next(one for one in self.snapshot["containers"] if one["name"] == "lan-map")
        bridge = next(one for one in self.snapshot["containers"] if one["name"] == "plane-web")
        extra = [{**host, "name": "photos", "project": "photos", "service": "photos",
                  "folder": "/volume1/docker/photos", "served": ""},
                 {**host, "name": "vaultwarden", "project": "vaultwarden", "service": "vaultwarden",
                  "folder": "/volume1/docker/vaultwarden", "served": "vault.lan.example"},
                 {**bridge, "name": "git_forgejo", "project": "forgejo", "service": "forgejo",
                  "folder": "/volume1/docker/forgejo", "image": "codeberg.org/forgejo/forgejo:14.0.2",
                  "ports": ["2222→22/tcp", "3000→3000/tcp"], "host_ports": [2222, 3000],
                  "served": "git.lan.example"}]
        gate = {"missing": "", "firewall": {"missing": "", "on": False, "profile": "default", "rules": 0}, "doors": [
            {"name": "photos.lan.example", "ports": [443], "to": "http://127.0.0.1:18140", "profile": None},
            {"name": "map.lan.example", "ports": [443], "to": "http://localhost:18091", "profile": None},
            {"name": "caravan.lan.example", "ports": [443], "to": "http://192.168.30.20:7990", "profile": None},
            {"name": "git.lan.example", "ports": [443], "to": "http://localhost:3000", "profile": None},
            {"name": "plane.lan.example", "ports": [443], "to": "http://localhost:8810", "profile": None}]}
        return self.told(snapshot={**self.snapshot, "containers": self.snapshot["containers"] + extra, "gate": gate})

    def test_a_container_in_the_hosts_network_gets_its_port_by_label_or_by_its_one_name(self):
        """lan-map by its label, photos by its name; vaultwarden's label names no door, and no
        door is guessed for it; a container in Docker's own network has its ports from Docker."""
        api = self.with_proxy().api()
        proxy = {one["name"]: one["proxy"] for entry in api["projects"] for one in entry["containers"]}
        self.assertEqual((proxy["lan-map"], proxy["photos"]),
                         ({"name": "map.lan.example", "port": 18091}, {"name": "photos.lan.example", "port": 18140}))
        self.assertEqual((proxy["vaultwarden"], proxy["plane-web"]), (None, None))
        self.assertEqual([(row["port"], row["name"], row["nas"]) for row in api["proxied"]],
                         [(3000, "git.lan.example", True), (7990, "caravan.lan.example", False),
                          (8810, "plane.lan.example", True), (18091, "map.lan.example", True),
                          (18140, "photos.lan.example", True)])

    def test_a_label_names_the_door_in_dockers_own_network_too_and_a_name_alone_does_not(self):
        """Forgejo publishes its ports and says its name by label: its door is the label's. Plane's
        name fits a door, but a project in Docker's own network is many containers: no door."""
        api = self.with_proxy().api()
        proxy = {one["name"]: one["proxy"] for entry in api["projects"] for one in entry["containers"]}
        self.assertEqual(proxy["git_forgejo"], {"name": "git.lan.example", "port": 3000})
        self.assertIsNone(proxy["plane-web"])
        text = self.with_proxy().markdown(Tongue.of("ru"))
        self.assertIn("| forgejo | forgejo | git_forgejo | codeberg.org/forgejo/forgejo:14.0.2 | работает | запускается |"
                      " 2 ч 29 мин | 2222→22/tcp, 3000→3000/tcp; за прокси DSM: 3000 (git.lan.example) |", text)
        self.assertIn("| plane | web | plane-web | makeplane/plane-frontend:v0.24.1 | работает | запускается |"
                      " 2 ч 29 мин | 8810→3000/tcp |", text)

    def test_the_text_lists_the_ports_behind_the_proxy_port_name_where(self):
        text = self.with_proxy().markdown(Tongue.of("en"))
        self.assertIn("## Behind DSM's reverse proxy", text)
        self.assertIn("| 18091 | map.lan.example | the NAS itself |", text)
        self.assertIn("| 7990 | caravan.lan.example | another machine, 192.168.30.20 |", text)
        self.assertIn("| lan-map | lan-map | lan-map | lan-map:latest | running | healthy | 2h 29m |"
                      " host network; behind DSM's proxy: 18091 (map.lan.example) |", text)
        self.assertIn("| vaultwarden | vaultwarden | vaultwarden | lan-map:latest | running | healthy | 2h 29m | host network |", text)

    def free(self, snapshot: dict, listening: Listening = Listening(None, "free-port.no-tables")) -> dict:
        return self.told(snapshot=snapshot).free_port(listening)

    def with_gate(self, *doors: dict, extra: tuple = ()) -> dict:
        """The snapshot with these names behind the proxy, and these containers beside the rest."""
        return {**self.snapshot, "containers": self.snapshot["containers"] + list(extra),
                "gate": {"missing": "", "doors": list(doors)}}

    def test_the_free_port_is_none_of_the_proxys_none_of_dockers_and_none_the_host_listens_on(self):
        """18150 behind the proxy, 18160 published by Docker, 18170 listened on: 18180 is free.
        What the host listens on is told nowhere, neither in JSON nor in words."""
        bridge = next(one for one in self.snapshot["containers"] if one["name"] == "plane-web")
        snapshot = self.with_gate({"name": "new.lan.example", "ports": [443], "to": "http://127.0.0.1:18150", "profile": None},
                                  extra=({**bridge, "name": "busy", "ports": ["18160→80/tcp"], "host_ports": [18160]},))
        listening = Listening(frozenset({18170, 5432}))
        answer = self.free(snapshot, listening)
        self.assertEqual((answer["port"], answer["listening"], answer["missing"]), (18180, True, ""))
        text = self.told(snapshot=snapshot).markdown(Tongue.of("ru"), listening)
        self.assertIn("## Порт для нового приложения", text)
        self.assertIn("Следующий свободный порт: 18180. Его нет в таблице «За обратным прокси DSM» и среди портов"
                      " Docker, и машина его сейчас не слушает.", text)
        told = json.dumps(self.told(snapshot=snapshot).api(listening)) + text
        self.assertNotIn("18170", told)
        self.assertNotIn("5432", told)

    def test_without_the_hosts_tables_the_port_is_named_but_not_called_free(self):
        snapshot = self.with_gate()
        answer = self.free(snapshot)
        self.assertEqual((answer["port"], answer["listening"], answer["missing"]), (18150, False, "free-port.no-tables"))
        text = self.told(snapshot=snapshot).markdown(Tongue.of("ru"))
        self.assertIn("Следующий порт, которого нет в таблице «За обратным прокси DSM» и среди портов Docker: 18150."
                      " Слушает ли его машина, карта не знает. Таблиц TCP своей машины (/proc/net/tcp) карта не видит.", text)
        self.assertNotIn("свободный порт: 18150", text)

    def test_without_a_reading_of_the_proxy_no_port_is_named(self):
        """A port behind the proxy is taken while its app is stopped, and neither Docker nor the
        host can tell. A watcher older than its reading of the proxy is the same."""
        unread = {**self.snapshot, "gate": {"missing": "gate.not-mounted"}}
        answer = self.free(unread, Listening(frozenset()))
        self.assertEqual((answer["port"], answer["listening"], answer["missing"]), (None, None, "gate.not-mounted"))
        self.assertEqual(self.free(self.snapshot, Listening(frozenset()))["missing"], "gate.not-read")
        self.assertIn("The map names no free port. DSM on the NAS: its nginx folder is not mounted for the watcher",
                      self.told(snapshot=unread).markdown(Tongue.of("en"), Listening(frozenset())))

    def test_a_snapshot_older_than_the_host_ports_names_no_port(self):
        old = [{key: value for key, value in one.items() if key != "host_ports"} for one in self.snapshot["containers"]]
        answer = self.free({**self.with_gate(), "containers": old}, Listening(frozenset()))
        self.assertEqual((answer["port"], answer["missing"]), (None, "free-port.old-snapshot"))

    def test_with_every_port_taken_the_text_says_so(self):
        everything = Listening(frozenset(range(18150, 18991, 10)))
        self.assertEqual(self.free(self.with_gate(), everything)["missing"], "free-port.none-left")
        self.assertIn("Свободного порта от 18150 до 18990 с шагом 10 нет: все заняты.",
                      self.told(snapshot=self.with_gate()).markdown(Tongue.of("ru"), everything))

    def test_with_no_snapshot_the_free_port_says_why(self):
        with TemporaryDirectory() as empty:
            told = Containers.read(Path(empty) / "containers.json", TAKEN)
        self.assertEqual(told.api()["free_port"]["missing"], "containers.none")

    def test_with_no_reading_of_the_proxy_the_text_says_why(self):
        text = self.told(snapshot={**self.snapshot, "gate": {"missing": "gate.not-mounted"}}).markdown(Tongue.of("en"))
        self.assertIn("## Behind DSM's reverse proxy", text)
        self.assertIn("its nginx folder is not mounted for the watcher", text)

    def test_the_text_speaks_russian_when_asked(self):
        text = self.told().markdown(Tongue.of("ru"))
        self.assertIn("# Что работает на NAS01", text)
        self.assertIn("## Есть, но не запущены", text)
        self.assertIn("сеть хоста", text)


if __name__ == "__main__":
    unittest.main()

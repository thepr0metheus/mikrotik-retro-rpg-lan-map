import http.client
import json
import re
import shutil
import threading
import time
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from ipaddress import ip_network
from urllib.parse import quote
from pathlib import Path
from tempfile import TemporaryDirectory

from lan_map.access import Doorman
from lan_map.api_spec import ApiSpec
from lan_map.audience import Audience
from lan_map.containers import Watcher
from lan_map.refresh import Refresh
from lan_map.server import MapApp, RequestHandler
from lan_map.snapshot import Snapshot

BASE = Path(__file__).resolve().parent.parent
WEB, FIXTURE = BASE / "web", BASE / "fixtures" / "snapshot.json"
HOME, GUEST, ROUTER_ADDRESS = "192.168.88.10", "192.168.40.7", "192.168.88.1"


class Site:
    """A live server on a random port: the test talks to it exactly as a browser would."""

    def __init__(self, folder: Path, take=None, proxies=("127.0.0.0/8",), web=WEB, knocker=None):
        doorman = Doorman(show=[ip_network("192.168.88.0/24"), ip_network("192.168.20.0/24")],
                          move=[ip_network("192.168.88.0/24")], deny=[ip_network("192.168.88.1/32")],
                          trusted_proxies=[ip_network(net) for net in proxies])
        audience = Audience((ip_network("192.168.88.0/24"), ip_network("192.168.20.0/24")),
                            Path(folder) / "settings.json")
        doorman.show = audience.networks
        self.app = MapApp(web, folder, doorman, take=take, audience=audience, knocker=knocker)
        self.server = self.app.make_server("127.0.0.1", 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def ask(self, method, path, body=None, who=HOME, origin="own"):
        headers = {"X-Forwarded-For": who} if who else {}
        raw = None
        if body is not None:
            raw = json.dumps(body)
            headers["Content-Type"] = "application/json"
            headers["Origin"] = f"http://127.0.0.1:{self.port}" if origin == "own" else "http://foreign.example"
        link = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            link.request(method, path, raw, headers)
            answer = link.getresponse()
            payload = answer.read().decode("utf-8")
        finally:
            link.close()
        try:
            return answer.status, json.loads(payload)
        except json.JSONDecodeError:
            return answer.status, payload


class Watching:
    """A pretend container watcher: it answers the map's note the way the real one does — takes
    the note away first, then writes a snapshot taken after it."""

    def __init__(self, data: Path):
        self.data = data
        self.rounds = 0
        self.stopping = threading.Event()
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        note = self.data / Watcher.ASK
        while not self.stopping.wait(0.02):
            if note.exists():
                note.unlink()
                (self.data / "containers.json").write_text(json.dumps({
                    "taken": datetime.now(timezone.utc).isoformat(timespec="seconds"), "every": 3600,
                    "host": {"name": "NAS01"}, "apps": "", "folders": [], "containers": []}), encoding="utf-8")
                self.rounds += 1

    def stop(self):
        self.stopping.set()


class Deaf:
    """A pretend knock: the test never enters the network, it says which doors count as open."""

    def __init__(self, opened: dict):
        self.opened = opened
        self.asked: list = []

    def open_doors(self, ip: str) -> dict:
        self.asked.append(ip)
        return {"ip": ip, "from": "192.168.20.10", "knocked": 1, "took": 0.0,
                "open": [{"port": port, "name": name, "about": about}
                         for port, (name, about) in sorted(self.opened.items())]}


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.data = Path(self.folder.name)
        self.site = Site(self.data)
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.site.close)

    def with_snapshot(self):
        shutil.copy(FIXTURE, self.data / "snapshot.json")

    def with_walk(self, source: str, *targets: str, cache=()):
        """The fixture with live connections in it: the fixture itself holds none."""
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["tables"]["ip/firewall/connection"] = [
            {"src-address": f"{source}:51234", "dst-address": f"{target}:443", "protocol": "tcp"}
            for target in targets]
        payload["tables"]["ip/dns/cache"] = [
            {"name": name, "data": data, "type": "A"} for name, data in cache]
        (self.data / "snapshot.json").write_text(json.dumps(payload), encoding="utf-8")

    # --- who is out there beyond the sea ---------------------------------------------------------
    def test_the_page_of_houses_lists_who_is_known_and_who_is_not(self):
        """Nothing on it is typed: every line is a far end of the live walks, named or not."""
        self.with_walk("192.168.88.2", "213.157.200.141", "203.0.113.9",
                       cache=[("rr2.sn-h5bupjvh.googlevideo.com", "213.157.200.141")])
        status, payload = self.site.ask("GET", "/api/houses")
        self.assertEqual(status, 200)
        self.assertEqual(payload["known"],
                         [{"who": "YouTube", "by": "name", "count": 1, "addresses": 1}])
        self.assertEqual(payload["unknown"], [{"ip": "203.0.113.9", "count": 1}])

    def test_without_a_snapshot_the_empty_lists_say_why(self):
        """Empty because nobody is out there, and empty because nothing was looked at, differ."""
        status, payload = self.site.ask("GET", "/api/houses")
        self.assertEqual((status, payload["known"], payload["unknown"], payload["taken"]), (200, [], [], ""))
        self.assertTrue(payload["missing"])

    def test_with_a_snapshot_nothing_is_missing(self):
        self.with_walk("192.168.88.2", "203.0.113.9")
        payload = self.site.ask("GET", "/api/houses")[1]
        self.assertEqual(payload["missing"], "")
        self.assertTrue(payload["taken"])

    def test_nobody_writes_the_table_any_more(self):
        status, _ = self.site.ask("PUT", "/api/houses", {"houses": []})
        self.assertIn(status, (404, 405))

    def test_one_who_may_only_look_sees_the_page_whole(self):
        """There is nothing on it to change, so nothing on it to keep from a looker."""
        self.with_walk("192.168.88.2", "203.0.113.9")
        status, payload = self.site.ask("GET", "/api/houses", who="192.168.20.10")
        self.assertEqual((status, payload["unknown"]), (200, [{"ip": "203.0.113.9", "count": 1}]))

    def test_a_name_the_router_resolved_beats_a_guess_by_range(self):
        """That cache stands in a provider's own network, and it is still YouTube."""
        self.with_walk("192.168.88.2", "213.157.200.141",
                       cache=[("rr2.sn-h5bupjvh.googlevideo.com", "213.157.200.141")])
        walk = self.walk()
        self.assertEqual(walk["name"], "rr2.sn-h5bupjvh.googlevideo.com")
        self.assertEqual((walk["house"], walk["guessed"]), ("YouTube", False))

    def test_the_signpost_names_the_busiest_far_ends_as_the_services_page_does(self):
        """One reckoning for both: the signpost's planks are the top of the known list."""
        self.with_walk("192.168.88.2", "213.157.200.141", "203.0.113.9",
                       cache=[("rr2.sn-h5bupjvh.googlevideo.com", "213.157.200.141")])
        known = [one["who"] for one in self.site.ask("GET", "/api/houses")[1]["known"]]
        self.assertEqual(self.site.ask("GET", "/api/map")[1]["signpost"], known[:3])
        self.assertEqual(known, ["YouTube"])

    def test_with_no_connections_the_signpost_names_nobody(self):
        """A blank plank rather than a guessed name."""
        self.with_snapshot()
        self.assertEqual(self.site.ask("GET", "/api/map")[1]["signpost"], [])

    def walk(self) -> dict:
        """The one walk the snapshot holds."""
        trips = self.site.ask("GET", "/api/map")[1]["traffic"]["trips"]
        return [trip for walks in trips.values() for trip in walks][0]

    # --- the names the router answers itself ----------------------------------------------------
    def test_the_page_of_names_says_where_each_name_leads(self):
        """Every static record, grouped by its answer, with whoever on the map holds it."""
        self.with_snapshot()
        status, payload = self.site.ask("GET", "/api/names")
        self.assertEqual((status, payload["missing"]), (200, ""))
        self.assertTrue(payload["taken"])
        where = {place["to"]: place["where"] for place in payload["places"]}
        self.assertEqual(where["192.168.88.1"], "router")
        self.assertEqual(where["192.168.88.200"], "device")
        nas = next(place for place in payload["places"] if place["to"] == "192.168.88.200")
        self.assertIn("git.lan.example", [one["name"] for one in nas["names"]])
        self.assertTrue(all(asker["router"] for asker in payload["askers"]))

    def test_without_a_snapshot_the_names_say_why(self):
        """No names because the router holds none, and none because nothing was read, differ."""
        status, payload = self.site.ask("GET", "/api/names")
        self.assertEqual((status, payload["places"], payload["askers"], payload["taken"]),
                         (200, [], [], ""))
        self.assertTrue(payload["missing"])

    def test_the_names_obey_the_same_door_as_the_map(self):
        self.with_snapshot()
        self.assertEqual(self.site.ask("GET", "/api/names", who=GUEST)[0], 403)

    def test_the_guide_points_readers_at_the_names(self):
        payload = self.site.ask("GET", "/llms.txt")[1]
        self.assertIn("(/api/names)", payload)
        self.assertIn("(/names.html)", payload)

    def test_the_page_of_names_is_served(self):
        status, payload = self.site.ask("GET", "/names.html")
        self.assertEqual(status, 200)
        self.assertIn('src="names.js"', payload)

    # --- what runs on the map's host ------------------------------------------------------------
    def with_containers(self, taken: str):
        """What the watcher would have written: one running project, one never started."""
        (self.data / "containers.json").write_text(json.dumps({
            "taken": taken, "every": 3600,
            "host": {"name": "NAS01", "os": "Synology DSM", "docker": "24.0.2"},
            "apps": "/volume1/docker",
            "folders": [{"folder": "lan-map", "compose": "compose.yaml"},
                        {"folder": "xwiki", "compose": "compose.yaml"}],
            "containers": [{"name": "lan-map", "project": "lan-map", "service": "lan-map",
                            "folder": "/volume1/docker/lan-map", "image": "lan-map:latest",
                            "state": "running", "health": "healthy", "started": taken,
                            "finished": "", "exit_code": 0, "restarts": 0, "network": "host",
                            "ports": [], "host_ports": []}],
        }), encoding="utf-8")

    # --- the NAS's own gate ----------------------------------------------------------------------
    def with_gate(self):
        """The watcher's reading of DSM, beside its containers: one name behind a profile."""
        self.with_containers(datetime.now(timezone.utc).isoformat(timespec="seconds"))
        written = json.loads((self.data / "containers.json").read_text(encoding="utf-8"))
        written["gate"] = {"missing": "", "firewall": {"missing": "", "on": False, "profile": "default", "rules": 0},
                           "doors": [{"name": "vault.lan.example", "ports": [443], "to": "http://127.0.0.1:18100",
                                      "profile": [["allow", "192.168.88.0/24"], ["deny", "all"]]}]}
        (self.data / "containers.json").write_text(json.dumps(written), encoding="utf-8")

    def test_the_map_carries_dsms_gate_as_the_watcher_read_it_from_where_the_map_lives(self):
        """Who DSM turns away is worked out in lan_map.gate and tested there; here, that the
        reading and the map's own address reach the page."""
        self.with_snapshot()
        self.with_gate()
        self.site.app.here = lambda: "192.168.20.10"
        gate = self.site.ask("GET", "/api/map")[1]["gate"]
        self.assertEqual((gate["missing"], gate["here"], [door["name"] for door in gate["doors"]], gate["wall"]),
                         ("", "192.168.20.10", ["vault.lan.example"], "DSM's firewall is off."))

    def test_with_no_reading_of_the_gate_the_map_says_so_rather_than_draw_it_open(self):
        self.with_snapshot()
        gate = self.site.ask("GET", "/api/map")[1]["gate"]
        self.assertEqual((gate["missing"], gate["doors"]), ("gate.no-snapshot", []))

    def test_the_text_tells_the_gate_and_the_guide_points_at_it(self):
        self.with_snapshot()
        self.with_gate()
        text = self.site.ask("GET", "/network.md")[1]
        self.assertIn("## The NAS's own gate", text)
        self.assertIn("| vault.lan.example | the NAS itself, 127.0.0.1:18100 | allow 192.168.88.0/24, deny all |", text)
        self.assertIn("«The NAS's own gate» in /network.md", self.site.ask("GET", "/llms.txt")[1])

    def test_the_free_port_reads_what_the_host_listens_on(self):
        """The host listens on 18150, by its own TCP table: the next free port is 18160."""
        self.with_gate()
        tables = self.data / "net"
        tables.mkdir()
        (tables / "tcp").write_text("  sl  local_address rem_address   st\n"
                                    "   0: 0100007F:46E6 00000000:0000 0A 00000000:00000000\n", encoding="ascii")
        self.site.app.proc_net = tables
        free = self.site.ask("GET", "/api/containers")[1]["free_port"]
        self.assertEqual((free["port"], free["listening"]), (18160, True))
        self.assertIn("Следующий свободный порт: 18160.", self.site.ask("GET", "/containers.md?lang=ru")[1])

    # --- cards of characteristics -------------------------------------------------------------
    def test_every_device_is_listed_for_a_card_with_the_fields_a_card_holds(self):
        self.with_snapshot()
        status, answer = self.site.ask("GET", "/api/specs")
        self.assertEqual(status, 200)
        self.assertEqual(len(answer["devices"]), 48)
        self.assertEqual([field["key"] for field in answer["fields"]][:3], ["model", "os", "os_version"])
        self.assertEqual((answer["name_most"], answer["devices"][0]["specs"]), (48, None))

    def test_the_owner_writes_any_card_and_the_map_and_the_texts_tell_it(self):
        self.with_snapshot()
        status, card = self.site.ask("PUT", "/api/specs", {"device": "02:00:00:00:00:46", "os": "Ubuntu",
                                                           "cores": 8, "threads": 16, "by": "owner"})
        self.assertEqual((status, card["specs"]), (200, {"os": "Ubuntu", "cores": 8, "threads": 16}))
        self.assertEqual(card["by"], "owner")
        listed = self.site.ask("GET", "/api/specs")[1]["devices"]
        self.assertEqual(listed[0]["device"], "02:00:00:00:00:46", "cards come first")
        device = next(one for one in self.site.ask("GET", "/api/map")[1]["devices"] if one["key"] == "02:00:00:00:00:46")
        self.assertEqual(device["specs"][:3], ["System: Ubuntu", "Physical cores: 8", "Logical cores (threads): 16"])
        text = self.site.ask("GET", "/specs.md?lang=ru")[1]
        self.assertIn("## подпись-26 — 192.168.20.20", text)
        self.assertIn("- Система: Ubuntu", text)
        guide = self.site.ask("GET", "/llms.txt")[1]
        self.assertIn("(/specs.md)", guide)
        self.assertIn("(/api/specs)", guide)

    def test_the_owner_may_rename_a_device_from_its_card(self):
        self.with_snapshot()
        status, card = self.site.ask("PUT", "/api/specs", {"device": "02:00:00:00:00:46", "name": "build box"})
        self.assertEqual((status, card["name"], card["specs"]), (200, "build box", None))
        device = next(one for one in self.site.ask("GET", "/api/map")[1]["devices"] if one["key"] == "02:00:00:00:00:46")
        self.assertEqual((device["name"], device["specs"]), ("build box", []))

    def test_from_a_network_that_may_not_move_things_a_device_writes_only_its_own_card(self):
        """An agent writes down the machine it runs on; another machine's card, or the name on
        the map, is the owner's business."""
        self.with_snapshot()
        own = {"device": "02:00:00:00:00:3E", "os": "macOS", "by": "hermes"}
        self.assertEqual(self.site.ask("PUT", "/api/specs", own, who="192.168.20.10")[0], 200)
        status, refusal = self.site.ask("PUT", "/api/specs", {**own, "device": "02:00:00:00:00:46"}, who="192.168.20.10")
        self.assertEqual(status, 403)
        self.assertIn("192.168.20.10", refusal["error"])
        self.assertEqual(self.site.ask("PUT", "/api/specs", {**own, "name": "mine"}, who="192.168.20.10")[0], 403)
        self.assertEqual(self.site.ask("PUT", "/api/specs", own, who=GUEST)[0], 403)

    def test_a_card_is_refused_for_what_it_cannot_hold_and_for_nobody(self):
        self.with_snapshot()
        cases = [({"device": "02:00:00:00:00:46", "colour": "red"}, 400),
                 ({"device": "02:00:00:00:00:46", "cores": "eight"}, 400),
                 ({"device": "no-such-device", "os": "macOS"}, 404),
                 ({"device": "02:00:00:00:00:46"}, 400),
                 ({"os": "macOS"}, 400)]
        for body, status in cases:
            with self.subTest(body):
                self.assertEqual(self.site.ask("PUT", "/api/specs", body)[0], status)
        self.assertEqual(self.site.ask("PUT", "/api/specs", {"device": "02:00:00:00:00:46", "os": "x"},
                                       origin="foreign")[0], 403)
        self.assertFalse((self.data / "specs.json").exists(), "nothing refused was written")

    def test_the_cards_are_shown_only_to_those_shown_the_map(self):
        self.with_snapshot()
        self.assertEqual(self.site.ask("GET", "/api/specs", who=GUEST)[0], 403)
        self.assertEqual(self.site.ask("GET", "/specs.md", who=GUEST)[0], 403)

    def test_with_no_snapshot_the_cards_still_stand_and_say_why_the_devices_are_missing(self):
        status, answer = self.site.ask("GET", "/api/specs")
        self.assertEqual((status, answer["devices"]), (200, []))
        self.assertTrue(answer["missing"])

    def test_without_a_watcher_the_containers_say_so(self):
        """No snapshot is not an empty host: the text says the watcher has written nothing."""
        status, text = self.site.ask("GET", "/containers.md")
        self.assertEqual(status, 200)
        self.assertIn("No snapshot yet", text)
        self.assertEqual(self.site.ask("GET", "/api/containers")[1]["missing"], "containers.none")

    def test_what_runs_is_told_in_the_language_asked_for(self):
        self.with_containers(datetime.now(timezone.utc).isoformat(timespec="seconds"))
        text = self.site.ask("GET", "/containers.md?lang=ru")[1]
        self.assertIn("# Что работает на NAS01", text)
        self.assertIn("| xwiki | /volume1/docker/xwiki | compose.yaml | контейнеров нет |", text)
        payload = self.site.ask("GET", "/api/containers")[1]
        self.assertEqual({entry["project"]: entry["state"] for entry in payload["projects"]},
                         {"lan-map": "running", "xwiki": "not-started"})
        self.assertFalse(payload["stale"])

    def test_an_old_snapshot_is_called_stale(self):
        self.with_containers("2026-01-01T00:00:00+00:00")
        self.assertTrue(self.site.ask("GET", "/api/containers")[1]["stale"])
        self.assertIn("Stale:", self.site.ask("GET", "/containers.md")[1])

    def test_the_map_counts_what_its_watcher_saw_for_the_stack_by_its_yard(self):
        """The stack of containers says counts, not the list; with no snapshot, that it has none."""
        self.with_snapshot()
        self.assertEqual(self.site.ask("GET", "/api/map")[1]["docker"]["missing"], "containers.none")
        self.with_containers(datetime.now(timezone.utc).isoformat(timespec="seconds"))
        docker = self.site.ask("GET", "/api/map")[1]["docker"]
        self.assertEqual((docker["host"], docker["running"], docker["idle"], docker["unhealthy"], docker["stale"]),
                         ("NAS01", 1, 1, 0, False))

    def test_a_map_that_cannot_tell_its_own_address_says_nothing_rather_than_guess(self):
        self.with_snapshot()
        self.assertEqual(self.site.ask("GET", "/api/map")[1]["here"], "")
        self.assertEqual(MapApp.address_toward("256.1.1.1"), "")

    def test_the_containers_obey_the_same_door_as_the_map(self):
        self.assertEqual(self.site.ask("GET", "/containers.md", who=GUEST)[0], 403)
        self.assertEqual(self.site.ask("GET", "/api/containers", who=GUEST)[0], 403)

    def test_the_guide_points_readers_at_the_containers(self):
        payload = self.site.ask("GET", "/llms.txt")[1]
        self.assertIn("(/containers.md)", payload)
        self.assertIn("(/api/containers)", payload)

    def test_a_body_no_route_reads_is_not_taken_for_the_next_request(self):
        """The page asks for a refresh with `{}`, and the route reads nothing: on a kept
        connection those bytes would start the next request — `{}GET`, which no server knows."""
        link = http.client.HTTPConnection("127.0.0.1", self.site.port, timeout=5)
        statuses = []
        try:
            for _ in range(2):
                link.request("GET", "/healthz", "{}", {"X-Forwarded-For": HOME,
                                                        "Content-Type": "application/json"})
                answer = link.getresponse()
                answer.read()
                statuses.append(answer.status)
        finally:
            link.close()
        self.assertEqual(statuses, [200, 200])

    def test_the_packages_are_open_to_everyone_and_name_the_commit(self):
        """A check of known vulnerabilities reads them, like /healthz, from anywhere at home."""
        status, listing = self.site.ask("GET", "/api/packages", who=GUEST)
        self.assertEqual(status, 200)
        self.assertEqual(set(listing), {"version", "runtime", "os", "packages"})
        self.assertEqual(listing["version"], self.site.ask("GET", "/healthz")[1]["version"])
        self.assertEqual(listing["runtime"]["name"], "python")

    def test_health_names_the_commit_and_a_working_copy_has_none(self):
        """git archive writes the commit into VERSION; the repository holds the placeholder."""
        self.assertEqual(self.site.ask("GET", "/healthz"), (200, {"status": "ok", "version": None}))

    # --- the routes, described for whoever calls them --------------------------------------------
    def described(self) -> dict:
        status, document = self.site.ask("GET", "/openapi.json")
        self.assertEqual(status, 200)
        return document

    def operations(self):
        for path, operations in self.described()["paths"].items():
            for method, operation in operations.items():
                yield f"{method.upper()} {path}", operation

    def test_the_description_is_open_to_everyone_like_health(self):
        """Paths and words, nothing about the network: a guest may read it too."""
        status, document = self.site.ask("GET", "/openapi.json", who=GUEST)
        self.assertEqual((status, document["openapi"]), (200, "3.1.0"))

    def test_the_guide_points_readers_at_the_description(self):
        self.assertIn("(/openapi.json)", self.site.ask("GET", "/llms.txt")[1])

    def test_every_route_the_map_answers_is_described_and_nothing_else(self):
        """The server's own table and the pages beside the scripts: not one more, not one fewer."""
        pages = {"/" if page.name == "index.html" else f"/{page.name}" for page in WEB.glob("*.html")}
        table = {f"{method} {path}" for method, path in RequestHandler.ROUTES} | {f"GET {page}" for page in pages}
        self.assertEqual({name for name, _ in self.operations()}, table)

    def test_every_route_says_what_it_does_and_what_it_answers(self):
        for name, operation in self.operations():
            with self.subTest(name):
                self.assertTrue(operation["summary"], "a route nobody said a word about")
                self.assertIn("200", operation["responses"])
                self.assertEqual(operation["security"], [])

    def test_every_question_a_route_reads_has_words(self):
        for name, operation in self.operations():
            for question in operation.get("parameters", []):
                with self.subTest(f"{name} ?{question['name']}"):
                    self.assertNotEqual(question["description"], ApiSpec.NOT_DESCRIBED)

    def test_the_description_is_read_off_the_code_of_each_route(self):
        """The map reads ?at= and ?lang=; a change takes a JSON body and is turned away when not JSON."""
        paths = self.described()["paths"]
        self.assertEqual({one["name"] for one in paths["/api/map"]["get"]["parameters"]}, {"at", "lang"})
        self.assertNotIn("parameters", paths["/healthz"]["get"])
        self.assertIn("requestBody", paths["/api/layout"]["put"])
        self.assertEqual(set(paths["/api/layout"]["put"]["responses"]), {"200", "400", "403", "415"})
        self.assertEqual(set(paths["/api/map"]["get"]["responses"]), {"200", "403"})

    def test_the_description_names_the_version_health_names(self):
        """A copy made by git archive carries its commit, and both answers name it; a working
        copy has none, which health says as null and the description, wanting a string, in words."""
        self.assertEqual(self.described()["info"]["version"], "unknown")
        with TemporaryDirectory() as folder:
            built = Path(folder)
            shutil.copytree(WEB, built / "web")
            (built / "VERSION").write_text("abc1234\n", encoding="utf-8")
            site = Site(self.data, web=built / "web")
            try:
                self.assertEqual(site.ask("GET", "/healthz")[1]["version"], "abc1234")
                self.assertEqual(site.ask("GET", "/openapi.json")[1]["info"]["version"], "abc1234")
            finally:
                site.close()

    # --- the network in words ------------------------------------------------------------------
    def test_the_network_is_served_as_text_for_those_who_read(self):
        self.with_snapshot()
        status, payload = self.site.ask("GET", "/network.md")
        self.assertEqual(status, 200)
        self.assertTrue(payload.startswith("# "), payload[:40])
        self.assertIn("## Networks", payload)
        self.assertIn("## Who may go where", payload)

    def test_the_text_is_told_in_the_language_that_was_asked_for(self):
        """One snapshot, two tellings: `?lang=` decides, and the facts stay the same."""
        self.with_snapshot()
        russian = self.site.ask("GET", "/network.md?lang=ru")[1]
        self.assertIn("## Сети", russian)
        self.assertIn(self.site.ask("GET", "/api/map")[1]["taken"], russian)

    def test_the_languages_on_the_shelf_are_named(self):
        codes = [one["code"] for one in self.site.ask("GET", "/api/langs")[1]["langs"]]
        self.assertIn("en", codes)
        self.assertEqual(codes[0], "en", "English is the one the map falls back on")

    def test_the_guide_points_readers_at_the_text(self):
        status, payload = self.site.ask("GET", "/llms.txt")
        self.assertEqual(status, 200)
        self.assertIn("/network.md", payload)

    def test_the_text_obeys_the_same_door_as_the_map(self):
        """Whoever cannot see the map cannot see its retelling either."""
        self.with_snapshot()
        self.assertEqual(self.site.ask("GET", "/network.md", who=GUEST)[0], 403)
        self.assertEqual(self.site.ask("GET", "/llms.txt", who=GUEST)[0], 403)

    def test_asking_for_a_snapshot_that_is_not_on_the_shelf_is_refused(self):
        self.with_snapshot()
        status, _ = self.site.ask("GET", "/network.md?at=no-such.json")
        self.assertEqual(status, 404)

    # --- a device's doors ------------------------------------------------------------------------
    def test_the_scroll_gets_the_open_doors_of_a_known_device(self):
        self.with_snapshot()
        site = Site(self.data, knocker=Deaf({22: ("ssh", "door.22")}))
        self.addCleanup(site.close)
        status, payload = site.ask("POST", "/api/ports", {"ip": "192.168.88.2"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["open"], [{"port": 22, "name": "ssh", "about": "door.22"}])
        self.assertEqual(payload["ip"], "192.168.88.2")

    def test_the_map_refuses_to_knock_where_it_sees_nobody(self):
        """Otherwise the map would be a handy way to knock at another's door from its address."""
        self.with_snapshot()
        site = Site(self.data, knocker=Deaf({}))
        self.addCleanup(site.close)
        status, payload = site.ask("POST", "/api/ports", {"ip": "192.168.88.251"})
        self.assertEqual(status, 404)
        self.assertIn("no such device", payload["error"])
        self.assertEqual(site.app.knocker.asked, [], "no knocking was begun")

    def test_a_guest_may_look_but_not_knock(self):
        self.with_snapshot()
        site = Site(self.data, knocker=Deaf({}))
        self.addCleanup(site.close)
        status, _ = site.ask("POST", "/api/ports", {"ip": "192.168.88.2"}, who=GUEST)
        self.assertEqual(status, 403)

    def test_a_knock_from_another_page_is_refused(self):
        self.with_snapshot()
        site = Site(self.data, knocker=Deaf({}))
        self.addCleanup(site.close)
        status, _ = site.ask("POST", "/api/ports", {"ip": "192.168.88.2"}, origin="foreign")
        self.assertEqual(status, 403)

    # --- what is visible -------------------------------------------------------------------------
    def test_without_a_snapshot_the_map_says_so(self):
        status, payload = self.site.ask("GET", "/api/map")
        self.assertEqual(status, 503)
        self.assertIn("no snapshot of the network yet", payload["error"])

    def test_the_map_comes_whole(self):
        self.with_snapshot()
        status, payload = self.site.ask("GET", "/api/map")
        self.assertEqual(status, 200)
        self.assertEqual({"lang", "taken", "segments", "devices", "roads", "findings", "notes",
                          "ends", "outpost", "changes", "traffic", "signpost", "move", "layout",
                          "here", "docker", "gate", "refresh_on_open"},
                         set(payload))
        self.assertTrue(payload["segments"] and payload["roads"])

    def test_a_map_opened_on_an_old_snapshot_is_told_to_ask_for_a_fresh_one(self):
        """Nothing on a schedule asks the router: past ten minutes the page asks itself."""
        self.with_snapshot()
        taken = datetime(2026, 9, 20, 5, 35, 49, tzinfo=timezone.utc)
        self.site.app.clock = lambda: taken + timedelta(minutes=10)
        self.assertFalse(self.site.ask("GET", "/api/map")[1]["refresh_on_open"])
        self.site.app.clock = lambda: taken + timedelta(minutes=10, seconds=1)
        self.assertTrue(self.site.ask("GET", "/api/map")[1]["refresh_on_open"])

    def test_a_guest_is_not_shown_the_map(self):
        self.with_snapshot()
        status, payload = self.site.ask("GET", "/api/map", who=GUEST)
        self.assertEqual(status, 403)
        self.assertIn(GUEST, payload["error"])

    # --- what gets moved -------------------------------------------------------------------------
    def test_home_moves_things_and_they_stay(self):
        status, payload = self.site.ask("PUT", "/api/layout", {"places": {"router": [10, 20]}})
        self.assertEqual((status, payload["places"]), (200, {"router": [10.0, 20.0]}))
        self.assertEqual(self.site.ask("GET", "/api/layout")[1]["places"], {"router": [10.0, 20.0]})

    def test_the_lab_may_look_but_not_move(self):
        """Lab reaches the NAS by the router's masquerade. Looking yes, moving no."""
        self.with_snapshot()
        self.assertEqual(self.site.ask("GET", "/api/map", who=ROUTER_ADDRESS)[0], 200)
        status, payload = self.site.ask("PUT", "/api/layout", {"places": {}}, who=ROUTER_ADDRESS)
        self.assertEqual(status, 403)
        self.assertIn(ROUTER_ADDRESS, payload["error"])

    def test_a_request_from_a_foreign_page_moves_nothing(self):
        status, payload = self.site.ask("PUT", "/api/layout", {"places": {}}, origin="foreign")
        self.assertEqual(status, 403)
        self.assertFalse((self.data / "layout.json").exists())

    def test_nonsense_instead_of_places_is_refused(self):
        self.assertEqual(self.site.ask("PUT", "/api/layout", {"places": {"a": "тут"}})[0], 400)
        self.assertEqual(self.site.ask("PUT", "/api/layout", {"дома": {}})[0], 400)

    # --- a device's kind -------------------------------------------------------------------------
    def test_home_names_a_device_and_the_map_remembers_it(self):
        self.with_snapshot()
        status, payload = self.site.ask("PUT", "/api/device",
                                        {"device": "192.168.88.200", "name": "хранилище"})
        self.assertEqual((status, payload["name"]), (200, "хранилище"))
        named = [device for device in self.site.ask("GET", "/api/map")[1]["devices"]
                 if device["name"] == "хранилище"]
        self.assertTrue(named, "the map did not show the chosen name")

    def test_a_name_longer_than_a_signboard_is_refused(self):
        status, payload = self.site.ask("PUT", "/api/device",
                                        {"device": "192.168.88.200", "name": "и" * 60})
        self.assertEqual(status, 400)
        self.assertIn("longer than", payload["error"])

    def test_a_request_without_name_or_kind_is_refused(self):
        self.assertEqual(self.site.ask("PUT", "/api/device", {"device": "192.168.88.200"})[0], 400)

    def test_home_picks_an_icon_and_the_map_remembers_it(self):
        self.with_snapshot()
        status, payload = self.site.ask("PUT", "/api/device", {"device": "192.168.88.200", "kind": "nas"})
        self.assertEqual((status, payload["kind"]), (200, "nas"))
        chosen = [device for device in self.site.ask("GET", "/api/map")[1]["devices"]
                  if device["kind"] == "nas"]
        self.assertTrue(chosen, "the map did not show the chosen kind")

    def test_a_kind_without_a_picture_is_refused(self):
        status, payload = self.site.ask("PUT", "/api/device", {"device": "192.168.88.200", "kind": "тостер"})
        self.assertEqual(status, 400)
        self.assertIn("тостер", payload["error"])

    def test_an_icon_can_be_taken_back(self):
        self.site.ask("PUT", "/api/device", {"device": "192.168.88.200", "kind": "nas"})
        self.assertEqual(self.site.ask("PUT", "/api/device", {"device": "192.168.88.200", "kind": ""})[1]["kind"], "")
        self.assertEqual(json.loads((self.data / "atlas.json").read_text(encoding="utf-8"))["devices"], {})

    def test_a_guest_cannot_repaint_the_map(self):
        status, _ = self.site.ask("PUT", "/api/device", {"device": "192.168.88.200", "kind": "nas"}, who=GUEST)
        self.assertEqual(status, 403)
        self.assertFalse((self.data / "atlas.json").exists())

    # --- who may see -----------------------------------------------------------------------------
    def test_home_chooses_who_sees_the_map(self):
        self.with_snapshot()
        status, payload = self.site.ask("PUT", "/api/settings", {"show": ["192.168.88.0/24"]})
        self.assertEqual((status, payload["show"]), (200, ["192.168.88.0/24"]))
        self.assertEqual(self.site.ask("GET", "/api/map", who="192.168.20.7")[0], 403)
        self.assertEqual(self.site.ask("GET", "/api/map")[0], 200)

    def test_nobody_can_lock_himself_out(self):
        """You cannot shut yourself out: nobody would be left to tick the box back."""
        status, payload = self.site.ask("PUT", "/api/settings", {"show": ["192.168.20.0/24"]})
        self.assertEqual(status, 400)
        self.assertIn(HOME, payload["error"])

    def test_an_empty_list_is_refused(self):
        self.assertEqual(self.site.ask("PUT", "/api/settings", {"show": []})[0], 400)
        self.assertEqual(self.site.ask("PUT", "/api/settings", {"show": ["дом"]})[0], 400)

    def test_a_guest_cannot_open_the_map_to_everyone(self):
        status, _ = self.site.ask("PUT", "/api/settings", {"show": ["0.0.0.0/0"]}, who=GUEST)
        self.assertEqual(status, 403)

    # --- castles, how a yard looks, and the shelf of snapshots -------------------------------------
    def test_home_renames_a_castle_and_picks_its_colour(self):
        self.with_snapshot()
        status, payload = self.site.ask("PUT", "/api/segment",
                                        {"segment": "vlan30_iot", "title": "Датчики", "colour": "#1d9e75"})
        self.assertEqual((status, payload["title"]), (200, "Датчики"))
        titles = [segment["title"] for segment in self.site.ask("GET", "/api/map")[1]["segments"]]
        self.assertIn("Датчики", titles)

    def test_a_colour_that_is_not_a_colour_is_refused(self):
        status, payload = self.site.ask("PUT", "/api/segment", {"segment": "vlan30_iot", "colour": "синий"})
        self.assertEqual(status, 400)
        self.assertIn("is not a colour", payload["error"])

    def test_a_device_can_be_hidden_and_pinned(self):
        self.with_snapshot()
        self.assertEqual(self.site.ask("PUT", "/api/device",
                                       {"device": "192.168.88.200", "hidden": True})[1]["hidden"], True)
        hidden = [device for device in self.site.ask("GET", "/api/map")[1]["devices"] if device["hidden"]]
        self.assertTrue(hidden)
        self.assertEqual(self.site.ask("PUT", "/api/device",
                                       {"device": "192.168.88.200", "hidden": False})[1]["hidden"], False)

    def test_a_pin_is_yes_or_no_not_a_word(self):
        self.assertEqual(self.site.ask("PUT", "/api/device",
                                       {"device": "192.168.88.200", "pinned": "да"})[0], 400)

    def test_the_yard_remembers_how_it_was_folded(self):
        looks = {"bridge_main": {"folded": True, "sort": "name", "columns": 2}}
        status, payload = self.site.ask("PUT", "/api/layout", {"places": {}, "looks": looks})
        self.assertEqual((status, payload["looks"]), (200, looks))
        self.assertEqual(self.site.ask("PUT", "/api/layout",
                                       {"places": {}, "looks": {"bridge_main": {"sort": "как попало"}}})[0], 400)

    def test_the_island_can_be_made_bigger(self):
        status, payload = self.site.ask("PUT", "/api/layout", {"places": {}, "field": [2000, 1400]})
        self.assertEqual((status, payload["field"]), (200, [2000, 1400]))
        self.assertEqual(self.site.ask("GET", "/api/layout")[1]["field"], [2000, 1400])

    def test_an_island_the_size_of_a_continent_is_refused(self):
        self.assertEqual(self.site.ask("PUT", "/api/layout", {"places": {}, "field": [9000, 9000]})[0], 400)
        self.assertEqual(self.site.ask("PUT", "/api/layout", {"places": {}, "field": ["много"]})[0], 400)

    def test_the_shelf_keeps_snapshots_and_the_map_can_look_back(self):
        with TemporaryDirectory() as folder:
            data = Path(folder)
            site = Site(data, take=lambda: Snapshot.read(FIXTURE))
            self.addCleanup(site.close)
            self.watching(data)
            site.ask("POST", "/api/refresh")
            kept = site.ask("GET", "/api/history")[1]["kept"]
            self.assertEqual(len(kept), 1)
            self.assertIn("T", kept[0]["taken"])
            status, payload = site.ask("GET", f"/api/map?at={quote(kept[0]['name'])}")
            self.assertEqual((status, payload["taken"]), (200, kept[0]["taken"]))
            site.app.clock = lambda: datetime(2030, 1, 1, tzinfo=timezone.utc)
            self.assertFalse(site.ask("GET", f"/api/map?at={quote(kept[0]['name'])}")[1]["refresh_on_open"],
                             "a look back is not the present: nothing to refresh")

    def test_a_snapshot_that_is_not_on_the_shelf_is_refused(self):
        self.with_snapshot()
        self.assertEqual(self.site.ask("GET", "/api/map?at=../snapshot.json")[0], 404)

    # --- a fresh snapshot ------------------------------------------------------------------------
    def watching(self, data: Path) -> Watching:
        watcher = Watching(data)
        self.addCleanup(watcher.stop)
        return watcher

    def test_without_a_password_the_refresh_says_why(self):
        self.watching(self.data)
        status, payload = self.site.ask("POST", "/api/refresh")
        self.assertEqual((status, payload["fresh"], payload["snapshot"]["fresh"]), (503, False, False))
        self.assertIn("password", payload["snapshot"]["why"])
        self.assertIn("password", payload["error"])

    def test_the_previous_snapshot_is_kept_and_compared(self):
        """The old snapshot is not thrown away: it is what "what changed" is answered from."""
        self.with_snapshot()
        site = Site(self.data, take=lambda: Snapshot.read(FIXTURE))
        self.addCleanup(site.close)
        self.watching(self.data)
        self.assertEqual(site.ask("POST", "/api/refresh")[0], 200)
        self.assertTrue(Snapshot.before(self.data / "snapshot.json").is_file())
        changes = site.ask("GET", "/api/map")[1]["changes"]
        self.assertTrue(changes["before"], "nothing to compare with, though there is a previous one")

    def test_a_refresh_answers_once_both_snapshots_are_written(self):
        """No polling and no guessing: when the answer comes, the router's snapshot and the
        watcher's are both on disk, and the watcher's was taken after the call began."""
        with TemporaryDirectory() as folder:
            data = Path(folder)
            site = Site(data, take=lambda: Snapshot.read(FIXTURE))
            self.addCleanup(site.close)
            watcher = self.watching(data)
            began = datetime.now(timezone.utc).replace(microsecond=0)
            status, payload = site.ask("POST", "/api/refresh")
            self.assertEqual((status, payload["fresh"]), (200, True))
            self.assertEqual((payload["snapshot"]["walked"], payload["snapshot"]["taken"]),
                             (True, Snapshot.read(FIXTURE).taken))
            self.assertTrue((data / "snapshot.json").is_file())
            self.assertEqual((payload["containers"]["asked"], watcher.rounds), (True, 1))
            self.assertGreaterEqual(datetime.fromisoformat(payload["containers"]["taken"]), began)

    def test_a_snapshot_younger_than_half_a_minute_is_not_taken_again(self):
        """Many readers asking at once make one walk to the router, not one each."""
        walks = []

        def take():
            walks.append(1)
            fresh = Snapshot.read(FIXTURE)
            return Snapshot(datetime.now(timezone.utc).isoformat(timespec="seconds"), fresh.tables, fresh.missing)

        with TemporaryDirectory() as folder:
            data = Path(folder)
            site = Site(data, take=take)
            self.addCleanup(site.close)
            watcher = self.watching(data)
            first = site.ask("POST", "/api/refresh")[1]
            second = site.ask("POST", "/api/refresh")[1]
            self.assertEqual((first["snapshot"]["walked"], second["snapshot"]["walked"]), (True, False))
            self.assertEqual((second["containers"]["asked"], len(walks), watcher.rounds), (False, 1, 1))

    def test_one_walk_at_a_time_whoever_asks_during_it_waits_for_it(self):
        walks = []

        def slow():
            walks.append(1)
            time.sleep(0.3)
            fresh = Snapshot.read(FIXTURE)
            return Snapshot(datetime.now(timezone.utc).isoformat(timespec="seconds"), fresh.tables, fresh.missing)

        with TemporaryDirectory() as folder:
            data = Path(folder)
            site = Site(data, take=slow)
            self.addCleanup(site.close)
            self.watching(data)
            answers = []
            readers = [threading.Thread(target=lambda: answers.append(site.ask("POST", "/api/refresh")[0]))
                       for _ in range(3)]
            for reader in readers:
                reader.start()
            for reader in readers:
                reader.join()
            self.assertEqual((sorted(answers), len(walks)), ([200, 200, 200], 1))

    def test_a_watcher_that_stays_silent_is_named_not_waited_for_forever(self):
        with TemporaryDirectory() as folder:
            data = Path(folder)
            site = Site(data, take=lambda: Snapshot.read(FIXTURE))
            self.addCleanup(site.close)
            with mock.patch.object(Refresh, "WAIT", 0.3):
                status, payload = site.ask("POST", "/api/refresh")
            self.assertEqual((status, payload["snapshot"]["fresh"], payload["containers"]["fresh"]), (503, True, False))
            self.assertIn("watcher", payload["containers"]["why"])
            self.assertTrue((data / "snapshot.json").is_file(), "what could be taken anew still was")

    def test_a_script_may_refresh_without_the_pages_origin_and_a_guest_may_not(self):
        """curl -X POST is enough: it changes nothing but the snapshots' age. The door to the
        map itself still stands."""
        self.watching(self.data)
        self.assertEqual(self.site.ask("POST", "/api/refresh", who=GUEST)[0], 403)
        site = Site(self.data, take=lambda: Snapshot.read(FIXTURE))
        self.addCleanup(site.close)
        self.assertEqual(site.ask("POST", "/api/refresh")[0], 200)

    def test_a_router_that_refuses_is_quoted_not_hidden(self):
        def angry():
            raise RuntimeError("the router did not accept the password")

        with TemporaryDirectory() as folder:
            site = Site(Path(folder), take=angry)
            self.addCleanup(site.close)
            self.watching(Path(folder))
            status, payload = site.ask("POST", "/api/refresh")
            self.assertEqual(status, 503)
            self.assertIn("did not accept the password", payload["snapshot"]["why"])

    # --- the page's files ------------------------------------------------------------------------
    def test_a_stranger_cannot_call_himself_home(self):
        """A proxy appends X-Forwarded-For. From anyone who is not a proxy it is just words."""
        self.with_snapshot()
        site = Site(self.data, proxies=())
        self.addCleanup(site.close)
        status, payload = site.ask("GET", "/api/map", who=HOME)
        self.assertEqual(status, 403)
        self.assertIn("127.0.0.1", payload["error"])

    def test_only_the_kinds_of_file_a_page_is_made_of(self):
        with TemporaryDirectory() as folder:
            web = Path(folder)
            (web / "index.html").write_text("<p>карта</p>", encoding="utf-8")
            (web / "secrets.txt").write_text("секрет", encoding="utf-8")
            site = Site(self.data, web=web)
            self.addCleanup(site.close)
            self.assertEqual(site.ask("GET", "/")[0], 200)
            self.assertEqual(site.ask("GET", "/secrets.txt")[0], 404)

    def test_the_page_itself_is_served(self):
        status, payload = self.site.ask("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("<svg id=\"map\"", payload)

    def test_nothing_outside_web_is_served(self):
        for path in ("/../fixtures/snapshot.json", "/.hidden", "/../../etc/passwd"):
            with self.subTest(path):
                self.assertEqual(self.site.ask("GET", path)[0], 404)

    def test_the_map_links_only_to_what_the_server_serves(self):
        """Every way in drawn on the map leads to a real page: the notice board, the signpost,
        the stack of containers, and the book and the robot by the pier. The book's text is the
        snapshot told in words, so there has to be a snapshot to tell."""
        self.with_snapshot()
        code = (WEB / "map.js").read_text(encoding="utf-8")
        linked = set(re.findall(r"href: '(/[^'?#]*)'", code))
        self.assertLessEqual({"/names.html", "/houses.html", "/containers.md", "/network.md", "/llms.txt"},
                             linked)
        for path in linked:
            with self.subTest(path):
                self.assertEqual(self.site.ask("GET", path)[0], 200)

    def test_the_texts_are_ways_in_on_the_island_not_buttons_in_the_bar(self):
        """One way in to each text for people, on the map; the page's head still names them for agents."""
        page = (WEB / "index.html").read_text(encoding="utf-8")
        head, _, body = page.partition("</head>")
        for path in ("/network.md", "/llms.txt"):
            with self.subTest(path):
                self.assertIn(f'rel="alternate" type="text/markdown" href="{path}"', head)
                self.assertNotIn(f'href="{path}"', body)

    def test_the_pages_ask_only_where_the_server_answers(self):
        """Pages and server must agree on addresses: a mismatch is caught here, not in a browser.

        Every page, and an address written as a template too: up to its question mark."""
        asked = set()
        for path in WEB.glob("*.js"):
            asked |= set(re.findall(r"Api\.request\(\s*'(\w+)',\s*['`](/[^'`?$]+)",
                                    path.read_text(encoding="utf-8")))
        self.assertIn(("GET", "/api/names"), asked)
        self.assertIn(("GET", "/api/houses"), asked)
        self.assertEqual(asked - set(RequestHandler.ROUTES), set())


if __name__ == "__main__":
    unittest.main()

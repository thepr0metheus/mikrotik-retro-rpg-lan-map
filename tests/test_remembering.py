import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from lan_map.access import Doorman
from lan_map.memory import Memory
from lan_map.rounds import NameRounds
from lan_map.server import MapApp
from lan_map.settings import Settings, SettingsError
from lan_map.snapshot import Snapshot
from lan_map.tongue import Said, Tongue

from .samples import HOME, LAB, MEMBERS, SERVERS, lease, snapshot

WEB = Path(__file__).resolve().parent.parent / "web"
#: The clock every app here reads. The samples were taken half an hour before it.
NOW = datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc)
EARLIER = "2026-09-20T05:00:00+00:00"
#: Somewhere out there: TEST-NET-3, nobody's.
FAR = "203.0.113.5"


def cached(name, data):
    return {"name": name, "data": data, "type": "A", "ttl": "00:01:00"}


def world(cache=(), taken=None) -> Snapshot:
    """A home with one laptop talking to FAR, and whatever the router's cache holds."""
    one = snapshot(**{"ip/address": [HOME, LAB], "interface/list/member": MEMBERS,
                      "ip/dhcp-server": SERVERS,
                      "ip/dhcp-server/lease": [lease("192.168.88.10", "home", "AA:BB:CC:00:00:10",
                                                     name="laptop")],
                      "ip/firewall/connection": [{"src-address": "192.168.88.10:51234",
                                                  "dst-address": f"{FAR}:443", "protocol": "tcp"}],
                      "ip/dns/cache": list(cache)})
    return Snapshot(taken or one.taken, one.tables, one.missing)


def app(folder, take=None, ask=None) -> MapApp:
    return MapApp(WEB, Path(folder), Doorman((), (), (), ()), take=take, ask=ask, clock=lambda: NOW)


def walks_to(view: dict, address: str) -> list:
    return [walk for trips in view["traffic"]["trips"].values() for walk in trips
            if walk["to"] == address]


class RememberingTest(unittest.TestCase):
    def test_a_snapshot_leaves_its_names_in_memory(self):
        with TemporaryDirectory() as folder:
            site = app(folder, take=lambda: world([cached("far.example.com", FAR)]))
            site.refresh()
            self.assertEqual(site.memory.name(FAR), "far.example.com")
            self.assertEqual(Memory.read(Path(folder) / "names.json").name(FAR), "far.example.com")

    def test_the_map_signs_an_address_from_memory_once_the_cache_let_go(self):
        with TemporaryDirectory() as folder:
            world().write(Path(folder) / "snapshot.json")
            site = app(folder)
            site.remember(([cached("far.example.com", FAR)], EARLIER))
            walk, = walks_to(site.view(), FAR)
            self.assertEqual((walk["name"], walk["remembered"]), ("far.example.com", True))

    def test_the_cache_now_outranks_memory(self):
        with TemporaryDirectory() as folder:
            world([cached("now.example.com", FAR)]).write(Path(folder) / "snapshot.json")
            site = app(folder)
            site.remember(([cached("then.example.com", FAR)], EARLIER))
            walk, = walks_to(site.view(), FAR)
            self.assertEqual((walk["name"], walk["remembered"]), ("now.example.com", False))

    def test_an_address_with_a_name_moves_from_unknown_to_known_by_itself(self):
        """Nobody signs anything: the moment the router's name is remembered, it is known."""
        with TemporaryDirectory() as folder:
            world().write(Path(folder) / "snapshot.json")
            site = app(folder)
            self.assertEqual([one["ip"] for one in site.houses()["unknown"]], [FAR])
            site.remember(([cached("far.example.com", FAR)], EARLIER))
            self.assertEqual(site.houses()["unknown"], [])
            self.assertEqual(site.houses()["known"],
                             [{"who": "example.com", "by": "memory", "count": 1, "addresses": 1}])

    def test_stored_snapshots_seed_the_memory_and_the_newest_wins(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot.json"
            world([cached("old.example.com", FAR)], taken="2026-09-20T04:00:00+00:00").write(path)
            world([cached("new.example.com", FAR)], taken=EARLIER).write(path)
            site = app(folder)
            site.remember_stored()
            self.assertEqual(site.memory.name(FAR), "new.example.com")

    def test_an_unreadable_memory_is_set_aside_not_written_over(self):
        with TemporaryDirectory() as folder:
            (Path(folder) / "names.json").write_text("{not json", encoding="utf-8")
            site = app(folder)
            self.assertEqual(site.memory, Memory())
            self.assertEqual((Path(folder) / "names.json.unreadable").read_text(encoding="utf-8"),
                             "{not json")


class NameRoundsTest(unittest.TestCase):
    def test_a_round_reads_only_the_cache_and_writes_the_names_down(self):
        asked = []

        def ask(path):
            asked.append(path)
            return [cached("far.example.com", FAR)]

        with TemporaryDirectory() as folder:
            site = app(folder, ask=ask)
            self.assertTrue(NameRounds(site, 5).once())
            self.assertEqual(asked, ["ip/dns/cache"])
            self.assertEqual(site.memory.name(FAR), "far.example.com")
            self.assertFalse((Path(folder) / "snapshot.json").exists(), "no snapshot is taken")

    def test_a_silent_router_does_not_bring_the_round_down(self):
        def silent(path):
            raise RuntimeError("the router did not answer")

        with TemporaryDirectory() as folder:
            site = app(folder, ask=silent)
            self.assertFalse(NameRounds(site, 5).once())
            self.assertEqual(site.memory, Memory())

    def test_without_a_password_the_round_is_just_skipped(self):
        def nothing(path):
            raise SettingsError(Said.of("settings.no-password"))

        with TemporaryDirectory() as folder:
            self.assertFalse(NameRounds(app(folder, ask=nothing), 5).once())
            self.assertFalse(NameRounds(app(folder), 5).once())

    def test_names_are_not_looked_for_between_snapshots_unless_told_to(self):
        """Each look is a login the router writes into its log: off unless switched on."""
        base, password = Path("/opt/lan-map"), {"LAN_MAP_ROUTER_PASSWORD": "x"}
        self.assertEqual(Settings.from_env(password, base=base).names_minutes, 0)
        self.assertEqual(Settings.from_env({**password, "LAN_MAP_NAMES_MINUTES": "5"},
                                           base=base).names_minutes, 5)
        with self.assertRaises(SettingsError) as caught:
            Settings.from_env({**password, "LAN_MAP_NAMES_MINUTES": "often"}, base=base)
        self.assertIn("LAN_MAP_NAMES_MINUTES", Tongue.of("en").tell(caught.exception.said))


if __name__ == "__main__":
    unittest.main()

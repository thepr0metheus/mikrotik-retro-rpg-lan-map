import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lan_map.access import Doorman
from lan_map.rounds import Rounds
from lan_map.server import MapApp
from lan_map.settings import SettingsError
from lan_map.snapshot import Snapshot
from lan_map.tongue import Said

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "snapshot.json"
WEB = Path(__file__).resolve().parent.parent / "web"


def app(folder, take=None) -> MapApp:
    return MapApp(WEB, Path(folder), Doorman((), (), (), ()), take=take)


class RoundsTest(unittest.TestCase):
    def test_without_a_schedule_nobody_walks(self):
        with TemporaryDirectory() as folder:
            self.assertIsNone(Rounds(app(folder), 0).start())

    def test_one_round_takes_a_snapshot(self):
        with TemporaryDirectory() as folder:
            rounds = Rounds(app(folder, take=lambda: Snapshot.read(FIXTURE)), 60)
            self.assertTrue(rounds.once())
            self.assertTrue((Path(folder) / "snapshot.json").is_file())

    def test_a_router_that_kept_silent_does_not_bring_the_map_down(self):
        def angry():
            raise RuntimeError("the router did not answer")

        with TemporaryDirectory() as folder:
            self.assertFalse(Rounds(app(folder, take=angry), 60).once())
            self.assertFalse((Path(folder) / "snapshot.json").exists())

    def test_without_a_password_the_round_is_just_skipped(self):
        def nothing():
            raise SettingsError(Said.of("settings.no-password"))

        with TemporaryDirectory() as folder:
            self.assertFalse(Rounds(app(folder, take=nothing), 60).once())
            self.assertFalse(Rounds(app(folder), 60).once())


if __name__ == "__main__":
    unittest.main()

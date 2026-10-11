import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from lan_map.memory import Memory

MORNING, NOON = "2026-09-24T08:00:00+00:00", "2026-09-24T12:00:00+00:00"


def cached(name, data, kind="A"):
    return {"name": name, "data": data, "type": kind, "ttl": "00:04:33"}


class ReadingTest(unittest.TestCase):
    def test_one_reading_gives_each_address_its_shortest_name(self):
        rows = [cached("use1-pp-st-vs-sc.push.apple.com", "17.57.144.10"),
                cached("push.apple.com", "17.57.144.10"),
                cached("www.youtube.com", "youtube-ui.l.google.com", kind="CNAME")]
        self.assertEqual(Memory.resolved(rows), {"17.57.144.10": "push.apple.com"})


class LearningTest(unittest.TestCase):
    def test_what_the_cache_let_go_of_is_still_remembered(self):
        memory = Memory().learned([cached("connectivity-check.ubuntu.com", "185.125.190.99")], MORNING)
        memory = memory.learned([], NOON)
        self.assertEqual(memory.name("185.125.190.99"), "connectivity-check.ubuntu.com")

    def test_a_fresher_reading_wins(self):
        """The address was re-let in between: what stands there now is the newer name."""
        memory = (Memory().learned([cached("old.example.com", "203.0.113.5")], MORNING)
                  .learned([cached("new.example.com", "203.0.113.5")], NOON))
        self.assertEqual(memory.names["203.0.113.5"], ("new.example.com", NOON))

    def test_an_older_reading_read_again_changes_nothing_fresher(self):
        """At start the stored snapshots are read again; they must not undo a newer name."""
        memory = (Memory().learned([cached("new.example.com", "203.0.113.5")], NOON)
                  .learned([cached("old.example.com", "203.0.113.5")], MORNING))
        self.assertEqual(memory.names["203.0.113.5"], ("new.example.com", NOON))

    def test_a_name_nobody_saw_for_two_weeks_is_forgotten(self):
        memory = Memory().learned([cached("gone.example.com", "203.0.113.5"),
                                   cached("here.example.com", "203.0.113.6")], MORNING)
        memory = memory.learned([cached("here.example.com", "203.0.113.6")], "2026-10-07T12:00:00+00:00")
        later = memory.forgotten(datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))
        self.assertEqual(later.name("203.0.113.5"), "")
        self.assertEqual(later.name("203.0.113.6"), "here.example.com")

    def test_nothing_about_who_asked_is_kept(self):
        """An address, a name, a moment: the router's answer, not anybody's history."""
        memory = Memory().learned([cached("push.apple.com", "17.57.144.10")], MORNING)
        self.assertEqual(memory.names, {"17.57.144.10": ("push.apple.com", MORNING)})


class DiskTest(unittest.TestCase):
    def test_written_and_read_back_is_the_same(self):
        memory = Memory().learned([cached("push.apple.com", "17.57.144.10")], MORNING)
        with tempfile.TemporaryDirectory() as tmp:
            again = Memory.read(memory.write(Path(tmp) / "names.json"))
        self.assertEqual(again, memory)

    def test_no_file_is_an_empty_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(Memory.read(Path(tmp) / "names.json"), Memory())

    def test_a_broken_file_is_an_error_not_an_empty_memory(self):
        """Emptiness would be written over it at the next round, and two weeks gone unsaid."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                Memory.read(path)

    def test_the_file_is_a_plain_table(self):
        memory = Memory().learned([cached("push.apple.com", "17.57.144.10")], MORNING)
        with tempfile.TemporaryDirectory() as tmp:
            raw = json.loads(memory.write(Path(tmp) / "names.json").read_text(encoding="utf-8"))
        self.assertEqual(raw, {"names": {"17.57.144.10": ["push.apple.com", MORNING]}})


if __name__ == "__main__":
    unittest.main()

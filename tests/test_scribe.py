import unittest
from pathlib import Path

from lan_map.atlas import Atlas
from lan_map.scribe import Scribe, ago, cell, guide
from lan_map.snapshot import Snapshot
from lan_map.tongue import Tongue
from lan_map.view import View

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "snapshot.json"
EN = Tongue.of("en")


class WordsTest(unittest.TestCase):
    def test_a_span_becomes_words(self):
        self.assertEqual(ago("21w5d3h54m45s", EN), "seen 21w 5d ago")
        self.assertEqual(ago("1m36s", EN), "seen 1m 36s ago")

    def test_never_is_said_plainly(self):
        """The router's "never" means not "never switched on" but "never seen here"."""
        self.assertEqual(ago("never", EN), "not seen at this address yet")
        self.assertEqual(ago("", EN), "")

    def test_the_same_span_in_another_language(self):
        """One fact, two tellings: the dictionary decides, not the code that counted it."""
        self.assertEqual(ago("1m36s", Tongue.of("ru")), "видели 1 мин 36 с назад")

    def test_a_bar_inside_a_name_does_not_break_the_table(self):
        self.assertEqual(cell("Bob | Foreman"), "Bob \\| Foreman")
        self.assertEqual(cell(""), "—")


class StoryTest(unittest.TestCase):
    """The telling is built from a real snapshot: an invented one hides what life looks like."""

    def setUp(self):
        self.payload = View.of(Snapshot.read(FIXTURE), Atlas.empty()).payload()
        self.text = Scribe.of(self.payload).markdown()

    def test_it_says_when_it_was_taken(self):
        self.assertIn(self.payload["taken"], self.text)

    def test_every_network_is_named_with_its_addresses(self):
        for segment in self.payload["segments"]:
            with self.subTest(segment["key"]):
                self.assertIn(segment["network"], self.text)
                self.assertIn(segment["title"], self.text)

    def test_closed_roads_are_left_out_and_said_to_be_closed(self):
        """Listing the bans is pointless: there are more of them than permissions, and one rule."""
        shut = [road for road in self.payload["roads"] if road["width"] == "shut"]
        self.assertTrue(shut, "the sample should hold shut roads")
        self.assertIn("Whatever is not in this table is forbidden", self.text)

    def test_open_roads_are_all_there(self):
        for road in self.payload["roads"]:
            if road["width"] == "shut":
                continue
            with self.subTest(f"{road['source']}→{road['target']}"):
                self.assertIn(Scribe.of(self.payload).title(road["target"]), self.text)

    def test_devices_are_listed_with_their_addresses(self):
        named = [device for device in self.payload["devices"] if device["name"]][:5]
        for device in named:
            with self.subTest(device["name"]):
                self.assertIn(device["name"], self.text)

    def test_what_was_not_understood_is_said_out_loud(self):
        self.assertIn("What the map could not read", self.text)

    def test_it_points_at_the_machine_readable_twin(self):
        self.assertIn("/api/map", self.text)

    def test_the_text_is_markdown_with_tables(self):
        self.assertTrue(self.text.startswith("# "))
        self.assertIn("|---|", self.text)


class GuideTest(unittest.TestCase):
    def test_the_guide_sends_the_reader_to_the_text_first(self):
        text = guide()
        self.assertTrue(text.startswith("# "))
        self.assertIn("/network.md", text)
        self.assertIn("/api/map", text)
        self.assertIn("> ", text, "a signpost should open with a short description")

    def test_the_guide_warns_that_it_is_a_snapshot(self):
        self.assertIn("a snapshot, not a live network", guide())

    def test_the_guide_names_every_language_it_can_answer_in(self):
        """An agent must not have to guess: what it can ask for is written down."""
        text = guide()
        for code in ("en", "ru"):
            self.assertIn(f"?lang={code}", text)


if __name__ == "__main__":
    unittest.main()

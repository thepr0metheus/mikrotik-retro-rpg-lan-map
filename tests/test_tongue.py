"""The dictionaries, checked as strictly as the code.

A missing line is not a crash: the map says the key out loud and carries on. That is the right
behaviour at three in the morning and the wrong one in a repository, so the gap is caught here
instead. Everything a page or a server can ask for must be written down, in every language.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from lan_map.model import ARP, LEASE, NETMAP, PEER
from lan_map.ports import BY_UDP, DOORS, NAMES
from lan_map.roads import ALL, MOST, PORTS, PUZZLE, SHUT
from lan_map.specs import Specs
from lan_map.sprites import Sprites
from lan_map.tongue import HOME, PLAIN, Said, Tongue, known

ROOT = Path(__file__).resolve().parent.parent
#: Keys spelled out in the source. Whatever is built up from pieces is checked further down.
WRITTEN = re.compile(r"""(?:Said\.of|\bsay)\(\s*["']([a-zA-Z0-9._-]+)["']""")
MARKED = re.compile(r'data-say[a-z-]*="([a-zA-Z0-9._-]+)"')
HOLE = re.compile(r"\{(\w+)\}")
LINKS = Path(__file__).resolve().parent / "lang_check.js"
NODE = shutil.which("node")


def book(code: str) -> dict:
    return json.loads((HOME / f"{code}.json").read_text(encoding="utf-8"))


def asked_for() -> set:
    """Every key named outright in the map's own files."""
    found = set()
    for path in list((ROOT / "lan_map").glob("*.py")) + list((ROOT / "web").glob("*.js")):
        found |= set(WRITTEN.findall(path.read_text(encoding="utf-8")))
    for page in (ROOT / "web").glob("*.html"):
        found |= set(MARKED.findall(page.read_text(encoding="utf-8")))
    return found


class ShelfTest(unittest.TestCase):
    def test_english_comes_first_and_every_language_names_itself(self):
        shelf = known()
        self.assertTrue(shelf, "there is not a single dictionary")
        self.assertEqual(shelf[0]["code"], PLAIN)
        for one in shelf:
            with self.subTest(one["code"]):
                self.assertNotEqual(one["name"], one["code"], "the language has no name of its own")

    def test_every_language_says_the_same_things(self):
        """A key missing from a translation shows English; a key missing from English shows itself."""
        plain = book(PLAIN)
        for one in known():
            if one["code"] == PLAIN:
                continue
            with self.subTest(one["code"]):
                words = book(one["code"])
                self.assertEqual(set(words), set(plain), "the dictionaries have drifted apart")

    def test_the_holes_in_a_phrase_are_the_same_in_every_language(self):
        """A hole the translation forgot would show up as literal braces on the page."""
        plain = book(PLAIN)
        for one in known():
            words = book(one["code"])
            for key, text in plain.items():
                with self.subTest(lang=one["code"], key=key):
                    self.assertEqual(set(HOLE.findall(words.get(key, ""))), set(HOLE.findall(text)))


class EverythingIsWrittenDownTest(unittest.TestCase):
    """The point of this file: nothing the map can say may be missing from the dictionary."""

    def setUp(self):
        self.plain = book(PLAIN)

    def have(self, keys, about: str):
        for key in sorted(keys):
            with self.subTest(key):
                self.assertIn(key, self.plain, about)

    def test_every_key_named_in_the_source_is_in_the_dictionary(self):
        self.have(asked_for(), "the code asks for a phrase that was never written")

    def test_every_door_has_a_line(self):
        self.have({door.about for door in DOORS}, "a door with no caption")

    def test_every_door_named_by_a_key_has_that_key(self):
        """A door's name is a proper name (ssh, https) or a key. Only the key needs writing down."""
        self.have({name for name in list(NAMES.values()) + list(BY_UDP.values())
                   if "." in name}, "a door named by a word nobody wrote")

    def test_every_line_of_a_card_has_a_label_a_field_and_its_words(self):
        self.have({f"{part}.{key}" for key in Specs.keys() for part in ("specs.label", "specs.field")}
                  | {f"specs.line.{key}" for key in ("gpu", "role", "notes")}, "a line of a card nobody can name")

    def test_every_picture_has_a_name(self):
        self.have({f"kind.{kind}" for kind in Sprites.read().kinds},
                  "a picture nobody can name")

    def test_every_width_of_a_road_has_a_word(self):
        for kind in (ALL, MOST, PORTS, SHUT, PUZZLE):
            self.have({f"road.width.{kind}", f"md.width.{kind}"} - {"md.width.shut"},
                      "a road width with no word")

    def test_every_kind_of_finding_has_a_label(self):
        self.have({f"find.kind.{kind}" for kind in
                   ("no-rule", "mossy", "renamed", "dead-rule", "switched-off",
                    "nobody-rule", "puzzle")}, "a finding with no label")

    def test_every_way_a_device_is_seen_has_a_word(self):
        self.have({f"seen.{one}" for one in (LEASE, ARP, PEER, NETMAP)}, "a sighting with no word")


class SayingTest(unittest.TestCase):
    def test_an_unknown_key_comes_back_as_itself(self):
        """Better a visible key than a blank space: one is fixable, the other is a mystery."""
        self.assertEqual(Tongue.of(PLAIN).say("no.such.key"), "no.such.key")

    def test_a_hole_with_nothing_to_fill_it_stays_as_it_is(self):
        self.assertEqual(Tongue.of(PLAIN).say("find.dead-rule"),
                         "rules that never fired once: {count}")

    def test_a_language_we_do_not_have_falls_back_to_english(self):
        self.assertEqual(Tongue.of("xx").code, PLAIN)

    def test_a_phrase_inside_a_phrase_is_still_one_sentence(self):
        inner = Said.of("aside.ipsec")
        outer = Said.of("note.rule", index=24, why=inner)
        self.assertEqual(outer.by(Tongue.of(PLAIN)),
                         "rule 24: an IPsec rule: traffic between subnets does not go through it")

    def test_a_phrase_written_to_a_file_comes_back_the_same(self):
        """A snapshot outlives the run that took it, so a reason has to survive as plain JSON."""
        said = Said.of("router.no-answer", path="ip/arp", why="timeout")
        again = json.loads(json.dumps(said.payload()))
        self.assertEqual(Tongue.of(PLAIN).tell(again), said.by(Tongue.of(PLAIN)))


def linked(codes) -> dict:
    """How the page links a text in each of these languages, worked out by the real lang.js."""
    done = subprocess.run([NODE, str(LINKS), json.dumps(codes)], capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


@unittest.skipUnless(NODE, "node is not installed: the page's links cannot be checked")
class LinkingTest(unittest.TestCase):
    """The book, the robot and the crates open their texts in the page's language."""

    def test_english_asks_for_nothing(self):
        self.assertEqual(linked([PLAIN]), {PLAIN: "/llms.txt"})

    def test_every_other_language_asks_for_itself_and_the_server_answers_in_it(self):
        codes = [one["code"] for one in known() if one["code"] != PLAIN]
        self.assertTrue(codes, "a single dictionary: there is no other language to ask for")
        for code, link in linked(codes).items():
            with self.subTest(code):
                self.assertEqual(link, f"/llms.txt?lang={code}")
                self.assertEqual(Tongue.asked(code, "").code, code)


class ChoosingTest(unittest.TestCase):
    def test_what_was_asked_for_wins(self):
        self.assertEqual(Tongue.asked("ru", "en").code, "ru")

    def test_without_a_question_the_browser_is_listened_to(self):
        self.assertEqual(Tongue.asked("", "ru-RU,ru;q=0.9,en;q=0.8").code, "ru")

    def test_the_browser_is_read_in_its_own_order_of_preference(self):
        self.assertEqual(Tongue.listed("de;q=0.2,ru;q=0.9,en-GB;q=0.8"), ["ru", "en", "de"])

    def test_when_nobody_says_anything_it_is_english(self):
        self.assertEqual(Tongue.asked("", "").code, PLAIN)
        self.assertEqual(Tongue.asked("de", "fr").code, PLAIN)


if __name__ == "__main__":
    unittest.main()

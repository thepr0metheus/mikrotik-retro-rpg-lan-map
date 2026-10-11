import json
import shutil
import subprocess
import unittest
from pathlib import Path

from lan_map.sprites import SPRITES, Sprites

HARNESS = Path(__file__).resolve().parent / "sprites_check.js"
NODE = shutil.which("node")
def draw() -> dict:
    """What the page would draw: rectangles worked out by the real draughtsman."""
    done = subprocess.run([NODE, str(HARNESS)], capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def marks(rows) -> set:
    return {char for row in rows for char in row} - {"."}


class DataTest(unittest.TestCase):
    def setUp(self):
        self.sprites = Sprites.read()
        self.grids = dict(self.sprites.icons)

    def test_every_grid_is_a_rectangle(self):
        for name, rows in self.grids.items():
            with self.subTest(name):
                self.assertTrue(rows, "an empty grid")
                self.assertEqual(len({len(row) for row in rows}), 1, "rows of different lengths")

    def test_every_mark_has_a_colour(self):
        allowed = set(self.sprites.palette)
        for name, rows in self.sprites.icons.items():
            with self.subTest(name):
                self.assertLessEqual(marks(rows), allowed)

    def test_the_palette_has_no_spare_colours(self):
        used = set().union(*(marks(rows) for rows in self.grids.values()))
        self.assertEqual(set(self.sprites.palette) - used, set())

    def test_the_default_kind_is_one_of_the_set(self):
        self.assertIn(self.sprites.fallback, self.sprites.icons)


@unittest.skipUnless(NODE, "node is not installed: the page's draughtsman cannot be checked")
class DrawingTest(unittest.TestCase):
    """There is one draughtsman and it lives in JS. Python checks its work, never repeats it."""

    def setUp(self):
        self.sprites = Sprites.read()
        self.drawn = draw()

    def test_all_kinds_are_drawn(self):
        self.assertEqual(sorted(self.drawn["kinds"]), sorted(self.sprites.kinds))

    def test_each_kind_draws_exactly_its_own_pixels(self):
        for kind, rects in self.drawn["drawn"].items():
            with self.subTest(kind):
                painted = sum(len(row) - row.count(".") for row in self.sprites.icons[kind])
                self.assertEqual(sum(rect["width"] * rect["height"] for rect in rects), painted)
                self.assertLessEqual({rect["fill"] for rect in rects}, set(self.sprites.palette.values()))

    def test_neighbours_of_one_colour_join_into_one_strip(self):
        for kind, rects in self.drawn["drawn"].items():
            for first in rects:
                touching = [rect for rect in rects if rect["y"] == first["y"] and rect["fill"] == first["fill"]
                            and rect["x"] == first["x"] + first["width"]]
                self.assertEqual(touching, [], f"{kind}: two pieces of one colour side by side")

    def test_an_unknown_kind_draws_the_house(self):
        self.assertEqual(self.drawn["unknown"], self.drawn["drawn"][self.sprites.fallback])


if __name__ == "__main__":
    unittest.main()

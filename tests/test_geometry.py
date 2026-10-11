import json
import shutil
import subprocess
import unittest
from itertools import combinations
from pathlib import Path

HARNESS = Path(__file__).resolve().parent / "geometry_check.js"
NODE = shutil.which("node")

FOUR = [{"key": "home", "x": 1080, "y": 450, "houses": 25}, {"key": "lab", "x": 200, "y": 450, "houses": 12},
        {"key": "iot", "x": 640, "y": 750, "houses": 2}, {"key": "guests", "x": 640, "y": 150, "houses": 9}]
#: Castles dragged apart by a mouse so that the roads are bound to cross.
MOVED = [{"key": "home", "x": 1100, "y": 200, "houses": 25}, {"key": "lab", "x": 900, "y": 100, "houses": 12},
         {"key": "iot", "x": 640, "y": 750, "houses": 2}, {"key": "guests", "x": 200, "y": 450, "houses": 9}]
#: Four castles along one wall: a crowded junction.
CROWD = [{"key": f"дом{number}", "x": 1080, "y": 200 + number * 120, "houses": 4} for number in range(4)]
CROWD.append({"key": "lab", "x": 200, "y": 450, "houses": 4})


def ways(places) -> list:
    both = [[one["key"], other["key"]] for one, other in combinations(places, 2)]
    return both + [[other, one] for one, other in both]


ALL_WAYS = ways(FOUR)


def lay(places=FOUR, roads=None) -> dict:
    roads = ALL_WAYS if roads is None else roads
    done = subprocess.run([NODE, str(HARNESS), json.dumps(places), json.dumps(roads)],
                          capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def segments(points) -> list:
    return [(one, two) for one, two in zip(points, points[1:])
            if (one["x"], one["y"]) != (two["x"], two["y"])]


def crossing(first, second):
    """Where a lengthwise segment meets a crosswise one, or None."""
    (one, two), (three, four) = first, second
    flat = one["y"] == two["y"]
    if flat == (three["y"] == four["y"]):
        return None
    across, along = ((three, four), (one, two)) if flat else ((one, two), (three, four))
    x, y = across[0]["x"], along[0]["y"]
    if not min(along[0]["x"], along[1]["x"]) < x < max(along[0]["x"], along[1]["x"]):
        return None
    if not min(across[0]["y"], across[1]["y"]) < y < max(across[0]["y"], across[1]["y"]):
        return None
    return {"x": x, "y": y}


def under_a_bridge(at, bridges) -> bool:
    return any(deck["x"] <= at["x"] <= deck["x"] + deck["width"]
               and deck["y"] <= at["y"] <= deck["y"] + deck["height"]
               for deck in (mark["deck"] for mark in bridges))


@unittest.skipUnless(NODE, "node is not installed: the road layout cannot be checked")
class RoadsTest(unittest.TestCase):
    def test_every_road_goes_at_right_angles(self):
        for places in (FOUR, MOVED, CROWD):
            for lane in lay(places, ways(places))["lanes"]:
                for one, two in segments(lane["points"]):
                    with self.subTest(lane["road"]):
                        self.assertTrue(one["x"] == two["x"] or one["y"] == two["y"], "a road runs slantwise")

    def test_where_roads_do_cross_there_is_a_bridge(self):
        laid = lay()
        for first, second in combinations(laid["lanes"], 2):
            if first["corridor"] == second["corridor"]:
                continue
            for one in segments(first["points"]):
                for two in segments(second["points"]):
                    at = crossing(one, two)
                    if at:
                        self.assertTrue(under_a_bridge(at, laid["bridges"]),
                                        f"roads cross with no bridge at {at}")

    def test_a_castle_has_one_road_and_no_more(self):
        """Castles talk through the customs house, so a castle has one road: signs show the rest."""
        laid = lay()
        self.assertEqual(len(laid["lanes"]), len(FOUR))
        self.assertEqual(sorted(lane["corridor"] for lane in laid["lanes"]), list(range(len(FOUR))))

    def test_a_castle_keeps_every_road_that_touches_it(self):
        """One road, but it remembers every direction: width and signs come from those."""
        for lane in lay()["lanes"]:
            with self.subTest(lane["corridor"]):
                self.assertEqual(len(lane["road"].split(",")), (len(FOUR) - 1) * 2)

    def test_two_corridors_never_enter_the_town_by_one_gate(self):
        """Four castles on one side: each has its own gate, or the roads would merge at the wall."""
        for one, other in combinations(lay(CROWD, ways(CROWD))["corridors"], 2):
            if (one["flat"], one["side"]) != (other["flat"], other["side"]):
                continue
            apart = abs(one["along"] - other["along"])
            self.assertGreaterEqual(apart, (one["width"] + other["width"]) / 2,
                                    "one corridor's gate overlaps another's")

    def test_castles_dragged_together_get_their_bridge(self):
        """A human moves castles as they please. A crossing is inevitable, so a bridge is needed."""
        self.assertTrue(lay(MOVED)["bridges"], "the roads cross and there are no bridges")

    def test_a_busy_wall_makes_the_town_bigger(self):
        """Many castles on one side make a big junction, and it should look big."""
        few = lay(FOUR[:2], [["home", "lab"], ["lab", "home"]])
        busy = lay(CROWD, ways(CROWD))
        self.assertGreater(busy["town"]["height"], few["town"]["height"])


if __name__ == "__main__":
    unittest.main()

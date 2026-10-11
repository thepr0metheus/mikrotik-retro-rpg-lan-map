import unittest
from pathlib import Path

from lan_map.atlas import Atlas
from lan_map.roads import INTERNET, ROUTER
from lan_map.snapshot import Snapshot
from lan_map.view import View

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "snapshot.json"


class PayloadTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = Snapshot.read(FIXTURE)
        self.payload = View.of(self.snapshot, Atlas.empty()).payload()

    def test_every_road_leads_somewhere_the_page_knows(self):
        known = {segment["key"] for segment in self.payload["segments"]} | {INTERNET, ROUTER}
        for road in self.payload["roads"]:
            with self.subTest(f"{road['source']} → {road['target']}"):
                self.assertIn(road["source"], known)
                self.assertIn(road["target"], known)

    def test_each_shut_piece_comes_with_the_rules_that_shut_it(self):
        pier = next(road for road in self.payload["roads"]
                    if road["source"] == "vlan40_homenet" and road["target"] == INTERNET)
        self.assertTrue(pier["shutParts"])
        self.assertEqual(", ".join(part["where"] for part in pier["shutParts"]), pier["shutTo"])
        for part in pier["shutParts"]:
            with self.subTest(part["where"]):
                self.assertTrue(part["by"], "a piece shut by nobody")

    def test_the_yard_beyond_the_gate_is_marked_and_called_so(self):
        beyond = [segment for segment in self.payload["segments"] if segment["outside"]]
        self.assertEqual([(one["network"], one["title"]) for one in beyond], [("192.168.0.0/24", "beyond the gateway")])
        self.assertTrue(all(not segment["outside"] for segment in self.payload["segments"] if segment is not beyond[0]))

    def test_each_castle_gets_its_own_colour(self):
        colours = [segment["colour"] for segment in self.payload["segments"]]
        self.assertEqual(len(set(colours)), len(colours))

    def test_the_one_in_two_subnets_is_marked_as_standing_in_both(self):
        twins = [device for device in self.payload["devices"] if device["twin"]]
        self.assertEqual(len(twins), 1)
        self.assertEqual(len(twins[0]["homes"]), 2)

    def test_the_atlas_names_a_castle_and_a_device(self):
        atlas = Atlas(segments={"bridge_main": {"title": "Home", "colour": "#123456"}},
                      devices={"192.168.88.200": {"name": "NAS", "kind": "NAS"}})
        payload = View.of(self.snapshot, atlas).payload()
        home = next(segment for segment in payload["segments"] if segment["key"] == "bridge_main")
        self.assertEqual((home["title"], home["colour"]), ("Home", "#123456"))
        self.assertTrue(any(device["name"] == "NAS" and device["kind"] == "NAS"
                            for device in payload["devices"]))

    def test_a_kind_without_a_picture_is_named_not_hidden(self):
        atlas = Atlas(devices={"192.168.88.200": {"kind": "тостер"}})
        payload = View.of(self.snapshot, atlas).payload()
        toaster = next(device for device in payload["devices"] if device["kind"] == "тостер")
        self.assertFalse(toaster["known"])
        self.assertTrue(any("тостер" in note for note in payload["notes"]))


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lan_map.layout import Layout, LayoutError


class ReadingTest(unittest.TestCase):
    def test_no_file_means_nobody_moved_anything(self):
        with TemporaryDirectory() as folder:
            self.assertEqual(Layout.read(Path(folder) / "layout.json").places, {})

    def test_a_broken_file_is_said_out_loud(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "layout.json"
            path.write_text("{не json", encoding="utf-8")
            self.assertRaises(LayoutError, Layout.read, path)


class CheckingTest(unittest.TestCase):
    def test_a_place_is_two_numbers(self):
        self.assertEqual(Layout.checked({"router": [10, 20.25]}), {"router": [10.0, 20.2]})

    def test_a_place_named_by_an_older_map_keeps_its_spot(self):
        """The ends were renamed into codes; a layout written before that still means the same."""
        self.assertEqual(Layout.checked({"\u0440\u043e\u0443\u0442\u0435\u0440": [10, 20]}),
                         {"router": [10.0, 20.0]})

    def test_what_is_not_a_place_is_refused(self):
        for places in ([], {"": [1, 2]}, {"a": [1]}, {"a": "10,20"}, {"a": [1, True]},
                       {"a": [1, "2"]}, {"a": [0, 99999]}, {"a" * 200: [1, 2]}):
            with self.subTest(places):
                self.assertRaises(LayoutError, Layout.checked, places)

    def test_a_crowd_of_places_is_refused(self):
        self.assertRaises(LayoutError, Layout.checked, {str(number): [1, 2] for number in range(501)})


class WritingTest(unittest.TestCase):
    def test_what_was_written_reads_back(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "inner" / "layout.json"
            Layout({"замок": [1.5, 2.5]}).write(path)
            self.assertEqual(Layout.read(path).places, {"замок": [1.5, 2.5]})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["places"]["замок"], [1.5, 2.5])

    def test_no_half_written_leftovers(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "layout.json"
            Layout({"замок": [1, 2]}).write(path)
            self.assertEqual([file.name for file in Path(folder).iterdir()], ["layout.json"])


if __name__ == "__main__":
    unittest.main()

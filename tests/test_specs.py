"""Cards of characteristics: what a device is made of, as somebody wrote it down."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lan_map.atlas import Atlas
from lan_map.model import Device, Seat
from lan_map.specs import CardRefused, CardText, Specs, SpecsText
from lan_map.tongue import Tongue

NOW = "2026-10-10T18:00:00+00:00"
MAC, IP = "02:00:00:00:00:3E", "192.168.20.10"


def device(key=MAC, name="mac-mini", ips=(IP,), online=True) -> Device:
    return Device(key=key, name=name, kind="mac-mini",
                  seats=tuple(Seat(ip, "vlan20_nas", online, ("lease",), "") for ip in ips))


class WritingTest(unittest.TestCase):
    def test_lines_sent_are_set_empty_ones_wiped_and_the_rest_kept(self):
        first = Specs().with_card((MAC, IP), {"os": "macOS", "cores": 8, "ram_gb": 16}, "claude", NOW)
        second = first.with_card((MAC, IP), {"os": "", "os_version": "15.1"}, "", NOW)
        self.assertEqual(second.found(MAC)[1], {"os_version": "15.1", "cores": 8, "ram_gb": 16, "updated": NOW})

    def test_the_card_keeps_the_order_of_its_lines_and_says_who_and_when(self):
        card = Specs().with_card((MAC,), {"ram_gb": 16, "model": "Mac mini", "cpu": "Apple M1"}, "hermes", NOW).found(MAC)[1]
        self.assertEqual(list(card), ["model", "cpu", "ram_gb", "updated", "by"])
        self.assertEqual((card["updated"], card["by"]), (NOW, "hermes"))

    def test_a_card_written_by_address_moves_to_the_mac_once_the_router_knows_it(self):
        by_address = Specs().with_card((IP,), {"os": "macOS"}, "", NOW)
        moved = by_address.with_card((MAC, IP), {"cores": 8}, "", NOW)
        self.assertEqual(set(moved.cards), {MAC})
        self.assertEqual(moved.found(MAC)[1]["os"], "macOS")

    def test_a_card_left_with_no_lines_is_dropped(self):
        written = Specs().with_card((MAC,), {"os": "macOS"}, "", NOW)
        self.assertEqual(written.with_card((MAC,), {"os": None}, "", NOW).cards, {})

    def test_numbers_and_sizes_are_kept_as_numbers(self):
        card = Specs().with_card((MAC,), {"ram_gb": 15.5, "disks": [{"size_gb": 512.0, "type": " SSD   NVMe "}]},
                                 "", NOW).found(MAC)[1]
        self.assertEqual((card["ram_gb"], card["disks"]), (15.5, [{"size_gb": 512, "type": "SSD NVMe"}]))

    def test_whatever_has_no_place_on_a_card_is_refused_rather_than_dropped(self):
        refused = [
            {"colour": "red"},                       # no such line
            {"cores": "8"}, {"cores": True}, {"cores": 0}, {"cores": 1.5},
            {"ram_gb": -1}, {"ram_gb": 70000}, {"ram_gb": "16"},
            {"os": "x" * 61}, {"os": 7},
            {"disks": [{"size_gb": 0}]}, {"disks": [{"type": "SSD"}]}, {"disks": [{"size_gb": 1, "speed": 3}]},
            {"disks": [{"size_gb": 1}] * 17}, {"disks": "512 GB"},
        ]
        for fields in refused:
            with self.subTest(fields), self.assertRaises(CardRefused):
                Specs().with_card((MAC,), fields, "", NOW)
        with self.assertRaises(CardRefused):
            Specs().with_card((MAC,), {"os": "macOS"}, "x" * 61, NOW)

    def test_the_file_comes_back_as_it_was_written(self):
        written = Specs().with_card((MAC,), {"os": "macOS", "disks": [{"size_gb": 4000, "type": "HDD"}]}, "me", NOW)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "specs.json"
            written.write(path)
            self.assertEqual(Specs.read(path), written)
            self.assertEqual(Specs.read(Path(folder) / "none.json"), Specs())
            self.assertEqual(sorted(file.name for file in Path(folder).iterdir()), ["specs.json"])


class TellingTest(unittest.TestCase):
    def lines(self, card, code="en"):
        return CardText(card, Tongue.of(code)).lines()

    def test_a_card_is_told_line_by_line_and_signed(self):
        card = {"model": "Mac mini (M1, 2020)", "os": "macOS", "os_version": "15.1", "arch": "arm64",
                "cpu": "Apple M1", "cores": 8, "threads": 8, "ram_gb": 16, "ram_type": "LPDDR4X",
                "disks": [{"size_gb": 512, "type": "SSD"}, {"size_gb": 4000, "type": "HDD"}],
                "gpu": "Apple M1, 8 cores", "updated": NOW, "by": "hermes"}
        self.assertEqual(self.lines(card), [
            "Model: Mac mini (M1, 2020)", "System: macOS 15.1, arm64", "Processor: Apple M1",
            "Physical cores: 8", "Logical cores (threads): 8", "RAM: 16 GB, LPDDR4X",
            "Disks: 512 GB SSD; 4 TB HDD", "Graphics: Apple M1, 8 cores", "Written by hermes, 2026-10-10 18:00 UTC"])
        self.assertIn("ОЗУ: 16 ГБ, LPDDR4X", self.lines(card, "ru"))

    def test_an_empty_card_says_nothing(self):
        self.assertEqual(self.lines({}), [])

    def test_the_list_puts_cards_first_and_keeps_a_card_whose_device_is_gone(self):
        specs = Specs({MAC: {"os": "macOS", "updated": NOW}, "gone-key": {"os": "Ubuntu", "updated": NOW}})
        atlas = Atlas(devices={"gone-key": {"name": "old box"}})
        listed = specs.listed([device("02:00:00:00:00:99", "aaa", ("192.168.20.99",), False), device()],
                              atlas, Tongue.of("en"))
        self.assertEqual([(one["device"], one["present"], bool(one["specs"])) for one in listed],
                         [(MAC, True, True), ("gone-key", False, True), ("02:00:00:00:00:99", True, False)])
        self.assertEqual(listed[1]["name"], "old box")
        self.assertEqual(listed[0]["lines"], ["System: macOS", "Written 2026-10-10 18:00 UTC"])

    def test_the_text_for_agents_tells_the_cards_the_rest_and_how_to_write(self):
        specs = Specs({MAC: {"cpu": "Apple M1", "updated": NOW}})
        listed = specs.listed([device(), device("02:00:00:00:00:99", "", ("192.168.20.99",), False)],
                              Atlas(), Tongue.of("en"))
        text = SpecsText(listed, Tongue.of("en")).markdown()
        self.assertIn(f"## mac-mini — {IP}", text)
        self.assertIn(f"- Key: `{MAC}`", text)
        self.assertIn("- Processor: Apple M1", text)
        self.assertIn("## Without characteristics", text)
        self.assertIn("Devices: 1. nameless (192.168.20.99)", text)
        for key in ("device", "name", "by", *Specs.keys()):
            self.assertIn(f"- `{key}` — ", text)
        self.assertIn("PUT /api/specs", text)


if __name__ == "__main__":
    unittest.main()

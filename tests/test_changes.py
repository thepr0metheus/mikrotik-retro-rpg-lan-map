import unittest

from lan_map.atlas import Atlas
from lan_map.changes import Changes
from lan_map.tongue import Tongue

from .samples import HOME, LAB, MEMBERS, SERVERS, lease, rule, snapshot

EN = Tongue.of("en")


def said(changes) -> list:
    """The lines as English: what changed is decided first, and only then said out loud."""
    return [EN.tell(line) for line in changes.lines]


def world(leases=(), rules=(), addresses=(HOME,)) -> object:
    return snapshot(**{"ip/address": list(addresses), "ip/dhcp-server": SERVERS,
                       "interface/list/member": MEMBERS,
                       "ip/dhcp-server/lease": list(leases), "ip/firewall/filter": list(rules)})


PHONE = lease("192.168.88.10", "home", "AA:BB:CC:00:00:01", "телефон")
LAPTOP = lease("192.168.88.11", "home", "AA:BB:CC:00:00:02", "ноутбук")
DROP = rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24")


class ChangesTest(unittest.TestCase):
    def test_without_a_previous_snapshot_we_say_nothing(self):
        changes = Changes.between(None, world([PHONE]))
        self.assertEqual((changes.before, changes.lines), ("", ()))

    def test_a_new_house_and_a_gone_one(self):
        changes = Changes.between(world([PHONE]), world([LAPTOP]))
        self.assertTrue(any("arrived: ноутбук" in line for line in said(changes)))
        self.assertTrue(any("gone: телефон" in line for line in said(changes)))

    def test_a_house_that_only_went_offline(self):
        away = lease("192.168.88.10", "home", "AA:BB:CC:00:00:01", "телефон", status="waiting")
        changes = Changes.between(world([PHONE]), world([away]))
        self.assertTrue(any("left the network: телефон" in line for line in said(changes)))
        self.assertFalse(any(line.startswith("gone:") for line in said(changes)))

    def test_a_new_rule_and_a_removed_one(self):
        changes = Changes.between(world([PHONE]), world([PHONE], [DROP]))
        self.assertTrue(any("new rule" in line and "forward drop" in line for line in said(changes)))
        back = Changes.between(world([PHONE], [DROP]), world([PHONE]))
        self.assertTrue(any("rule removed" in line for line in said(back)))

    def test_a_rule_that_only_moved_is_not_a_change(self):
        """The router does read the order, but the condition stayed the same: no need to shout."""
        other = rule("accept", src_address="192.168.88.0/24", dst_address="192.168.20.30")
        changes = Changes.between(world([PHONE], [DROP, other]), world([PHONE], [other, DROP]))
        self.assertEqual([line for line in changes.lines if line.key.startswith("change.rule")], [])

    def test_a_castle_that_appeared(self):
        changes = Changes.between(world([PHONE]), world([PHONE], addresses=(HOME, LAB)))
        self.assertTrue(any("a subnet appeared: vlan20_lab" in line for line in said(changes)))

    def test_the_atlas_names_what_changed(self):
        named = Atlas(segments={"vlan20_lab": {"title": "Lab"}})
        changes = Changes.between(world([PHONE]), world([PHONE], addresses=(HOME, LAB)), named)
        self.assertTrue(any("a subnet appeared: Lab" in line for line in said(changes)))


if __name__ == "__main__":
    unittest.main()

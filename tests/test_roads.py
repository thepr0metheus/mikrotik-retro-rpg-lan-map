import unittest
from pathlib import Path

from lan_map.atlas import Atlas
from lan_map.model import Network
from lan_map.roads import ALL, INTERNET, MOST, PORTS, PUZZLE, ROUTER, SHUT, Roads
from lan_map.snapshot import Snapshot
from lan_map.tongue import Tongue

from .samples import HOME, LAB, MEMBERS, rule, snapshot

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "snapshot.json"
LAB_KEY, HOME_KEY = "vlan20_lab", "bridge_main"
EN = Tongue.of("en")


def said(lines) -> list:
    """Notes and signs as English: inside the map they travel as phrases without a language."""
    return [EN.tell(line) for line in lines]


def world(*rules, nat=(), lists=()) -> Roads:
    taken = snapshot(**{"ip/address": [HOME, LAB], "interface/list/member": MEMBERS,
                        "ip/firewall/filter": list(rules), "ip/firewall/nat": list(nat),
                        "ip/firewall/address-list": list(lists)})
    return Roads.of(taken, Network.of(taken, Atlas.empty()))


def road(*rules, source=LAB_KEY, target=HOME_KEY, **kinds):
    return world(*rules, **kinds).between(source, target)


class WidthTest(unittest.TestCase):
    def test_without_a_rule_the_road_is_open_and_the_map_says_why(self):
        """RouterOS forward lets through by default. That must be shown, not passed over."""
        roads = world()
        open_road = roads.between(LAB_KEY, HOME_KEY)
        self.assertEqual(open_road.width, ALL)
        self.assertTrue(open_road.by_default)
        self.assertIn(f"{LAB_KEY} → {HOME_KEY}",
                      [EN.tell(finding.said).split(":")[0] for finding in roads.findings])

    def test_a_drop_closes_the_road(self):
        shut = road(rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24"))
        self.assertEqual(shut.width, SHUT)
        self.assertEqual(shut.openings, ())

    def test_an_accept_and_a_drop_leave_a_path(self):
        path = road(rule("accept", src_address="192.168.20.0/24", dst_address="192.168.88.200",
                         protocol="tcp", dst_port="445", packets="12"),
                    rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24"))
        self.assertEqual(path.width, PORTS)
        self.assertEqual(said(path.signs), ["tcp 445"])
        self.assertEqual(path.openings[0].target, "192.168.88.200")
        self.assertEqual(path.openings[0].rules[0].packets, 12)

    def test_the_first_rule_wins(self):
        """Rules are read in order. The same set in another order is another road."""
        rules = (rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24"),
                 rule("accept", src_address="192.168.20.0/24", dst_address="192.168.88.200",
                      protocol="tcp", dst_port="445"))
        self.assertEqual(road(*rules).width, SHUT)
        self.assertEqual(road(*reversed(rules)).width, PORTS)

    def test_a_switched_off_rule_decides_nothing(self):
        self.assertEqual(road(rule("drop", src_address="192.168.20.0/24",
                                   dst_address="192.168.88.0/24", disabled="true")).width, ALL)

    def test_an_answer_in_a_started_talk_opens_nothing(self):
        """established and related answer inside a conversation already begun, not a new road."""
        shut = road(rule("accept", connection_state="established,related"),
                    rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24"))
        self.assertEqual(shut.width, SHUT)

    def test_an_unknown_condition_is_not_an_open_road(self):
        puzzle = road(rule("accept", src_address="192.168.20.0/24", content="minecraft"),
                      rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24"))
        self.assertEqual(puzzle.width, PUZZLE)
        self.assertTrue(any("content" in note for note in said(world(
            rule("accept", src_address="192.168.20.0/24", content="minecraft")).notes)))

    def test_a_rule_we_cannot_read_never_turns_into_a_closed_road(self):
        """"Unread" is not "shut": a shut road is simply not drawn on the map."""
        self.assertNotEqual(road(rule("drop", src_address="192.168.20.0/24", content="x")).width, SHUT)


class WhoTest(unittest.TestCase):
    def test_only_the_named_hosts_get_through(self):
        path = road(rule("accept", src_address="192.168.20.10-192.168.20.11",
                         dst_address="192.168.88.200", protocol="tcp", dst_port="445"),
                    rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24"))
        self.assertEqual([opening.source for opening in path.openings], ["192.168.20.10-192.168.20.11"])

    def test_an_empty_address_list_matches_nobody(self):
        """The list exists and holds no addresses. In the router such a rule never fires."""
        roads = world(rule("accept", src_address_list="друзья", dst_address="192.168.88.200"),
                      rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24"),
                      lists=[{"list": "другой", "address": "192.168.20.5", "disabled": "false"}])
        self.assertEqual(roads.between(LAB_KEY, HOME_KEY).width, SHUT)
        self.assertTrue(any(finding.kind == "nobody-rule" for finding in roads.findings))

    def test_a_list_with_addresses_opens_the_road_for_them(self):
        path = road(rule("accept", src_address_list="друзья", dst_address="192.168.88.200",
                         protocol="tcp", dst_port="445"),
                    rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24"),
                    lists=[{"list": "друзья", "address": "192.168.20.5", "disabled": "false"}])
        self.assertEqual([opening.source for opening in path.openings], ["192.168.20.5"])

    def test_everyone_except_an_empty_list_is_everyone(self):
        """
        `!list` over a list nobody ever filled lets everybody through — the opposite of the
        same list without the mark. Read the other way round, the map hides a wide-open road
        and swears the door is shut, which is worse than saying nothing at all.
        """
        roads = world(rule("accept", src_address_list="!враги", dst_address="192.168.88.200"),
                      rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24"),
                      lists=[{"list": "другой", "address": "192.168.20.5", "disabled": "false"}])
        path = roads.between(LAB_KEY, HOME_KEY)
        self.assertEqual((path.width, [opening.source for opening in path.openings]),
                         (MOST, ["192.168.20.0/24"]))

    def test_everyone_except_the_listed_hosts(self):
        path = road(rule("accept", src_address_list="!враги", dst_address="192.168.88.200",
                         protocol="tcp", dst_port="445"),
                    rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24"),
                    lists=[{"list": "враги", "address": "192.168.20.5", "disabled": "false"}])
        self.assertEqual([opening.source for opening in path.openings],
                         ["192.168.20.0-192.168.20.4, 192.168.20.6-192.168.20.255"])

    def test_everyone_except_this_address(self):
        """The mark belongs to `src-address` too, not only to lists and interfaces."""
        path = road(rule("accept", src_address="!192.168.20.5", dst_address="192.168.88.200",
                         protocol="tcp", dst_port="445"),
                    rule("drop", src_address="192.168.20.0/24", dst_address="192.168.88.0/24"))
        self.assertEqual([opening.source for opening in path.openings],
                         ["192.168.20.0-192.168.20.4, 192.168.20.6-192.168.20.255"])

    def test_everyone_except_these_interfaces(self):
        """`!LAN` means "through any but these". Home is on the LAN list, Lab is not."""
        rules = (rule("accept", chain="input", protocol="udp", dst_port="53"),
                 rule("drop", chain="input", in_interface_list="!LAN"))
        roads = world(*rules)
        self.assertEqual(roads.between(HOME_KEY, ROUTER).width, ALL)
        lab = roads.between(LAB_KEY, ROUTER)
        self.assertEqual((lab.width, said(lab.signs)), (PORTS, ["udp 53"]))


class PierTest(unittest.TestCase):
    def test_the_way_out_is_open_except_where_it_is_not(self):
        roads = world(rule("drop", src_address="192.168.20.0/24", dst_address="10.0.0.0/8"),
                      rule("accept", src_address="192.168.20.0/24", out_interface_list="WAN"))
        pier = roads.between(LAB_KEY, INTERNET)
        self.assertEqual(pier.width, MOST)
        self.assertEqual(pier.shut_to, "10.0.0.0/8")

    def test_each_shut_piece_names_the_rules_that_shut_it_there(self):
        """Two rules shut two networks: each network is told its own rule, not both of them."""
        roads = world(rule("drop", src_address="192.168.20.0/24", dst_address="10.0.0.0/8", comment="ten"),
                      rule("drop", src_address="192.168.20.0/24", dst_address="192.168.0.0/24",
                           comment="tp-link"),
                      rule("accept", src_address="192.168.20.0/24", out_interface_list="WAN"))
        pier = roads.between(LAB_KEY, INTERNET)
        self.assertEqual(pier.width, MOST)
        self.assertEqual([(piece.where, [one.comment for one in piece.rules]) for piece in pier.shut],
                         [("10.0.0.0/8", ["ten"]), ("192.168.0.0/24", ["tp-link"])])
        self.assertEqual(pier.shut_to, "10.0.0.0/8, 192.168.0.0/24")

    def test_a_name_changed_on_the_way_is_said_out_loud(self):
        roads = world(nat=[{"chain": "srcnat", "action": "masquerade", "packets": "5",
                            "src-address": "192.168.20.0/24", "out-interface": "bridge_main"}])
        self.assertTrue(roads.between(LAB_KEY, HOME_KEY).renamed)
        self.assertTrue(any(finding.kind == "renamed" for finding in roads.findings))


class AsideTest(unittest.TestCase):
    """What the map does not count it says out loud — without frightening anyone needlessly."""

    def notes(self, **tables) -> tuple:
        taken = snapshot(**{"ip/address": [HOME, LAB], "interface/list/member": MEMBERS, **tables})
        return Roads.of(taken, Network.of(taken, Atlas.empty())).notes

    def test_a_rule_in_raw_is_named_because_we_do_not_read_it(self):
        notes = self.notes(**{"ip/firewall/raw": [rule("drop", chain="prerouting")]})
        self.assertTrue(any("raw" in note and "1" in note for note in said(notes)))

    def test_a_counter_in_mangle_scares_nobody(self):
        """A bookkeeping counter changes no packet's fate, and that is what should be said."""
        notes = self.notes(**{"ip/firewall/mangle": [rule("passthrough", chain="forward")]})
        self.assertTrue(any("bookkeeping counters" in note for note in said(notes)))

    def test_a_missing_table_is_not_the_same_as_an_empty_one(self):
        bare = snapshot(**{"ip/address": [HOME]})
        without = Snapshot(bare.taken, {key: value for key, value in bare.tables.items()
                                        if key != "ip/firewall/raw"}, {})
        notes = Roads.of(without, Network.of(without, Atlas.empty())).notes
        self.assertTrue(any("holds no" in note and "raw" in note for note in said(notes)))
        self.assertFalse(any("raw" in note for note in said(self.notes())))

    def test_a_living_ipsec_policy_is_a_reason_to_look_closer(self):
        alive = self.notes(**{"ip/ipsec/policy": [{"template": "false", "disabled": "false"}]})
        self.assertTrue(any("may well fire" in note for note in said(alive)))
        template = self.notes(**{"ip/ipsec/policy": [{"template": "true"}]})
        self.assertTrue(any("only the template" in note for note in said(template)))


class RealRulesTest(unittest.TestCase):
    """Real rules from the house: such a tangle could never be invented for a test."""

    def setUp(self):
        snapshot = Snapshot.read(FIXTURE)
        self.roads = Roads.of(snapshot, Network.of(snapshot, Atlas.empty()))

    def road(self, source, target):
        return self.roads.between(source, target)

    def test_lab_reaches_home_only_through_named_ports_of_the_nas(self):
        lab = self.road("vlan20_lab", "bridge_main")
        self.assertEqual(lab.width, PORTS)
        self.assertEqual(set(said(lab.signs)),
                         {"icmp", "tcp 443", "tcp 445", "tcp 2222", "tcp 3000", "tcp 8065"})
        self.assertEqual({opening.target for opening in lab.openings}, {"192.168.88.200"})

    def test_lab_and_iot_do_not_see_each_other(self):
        self.assertEqual(self.road("vlan20_lab", "vlan30_iot").width, SHUT)
        self.assertEqual(self.road("vlan30_iot", "vlan20_lab").width, SHUT)

    def test_lab_reaches_the_guests_because_nobody_forbade_it(self):
        """A finding: there is no "Lab → guests" rule at all, and RouterOS lets through."""
        guests = self.road("vlan20_lab", "vlan40_homenet")
        self.assertEqual((guests.width, guests.by_default), (ALL, True))

    def test_the_guests_road_to_the_lab_is_the_minecraft_one_and_it_is_mossy(self):
        road = self.road("vlan40_homenet", "vlan20_lab")
        self.assertEqual({opening.target for opening in road.openings}, {"192.168.20.30"})
        self.assertEqual(set(said(road.signs)), {"tcp 25565", "tcp 25566", "tcp 25567",
                                                 "udp 19132", "udp 19133", "udp 19134"})
        self.assertTrue(road.dead, "the rules are there and have never fired")

    def test_the_guests_go_out_but_not_into_private_networks(self):
        pier = self.road("vlan40_homenet", INTERNET)
        self.assertEqual(pier.width, MOST)
        for network in ("10.0.0.0/8", "172.16.0.0/12"):
            self.assertIn(network, pier.shut_to)

    def test_home_talks_to_the_router_freely_and_the_others_by_ports(self):
        self.assertEqual(self.road("bridge_main", ROUTER).width, ALL)
        lab = self.road("vlan20_lab", ROUTER)
        self.assertEqual(lab.width, PORTS)
        self.assertIn("udp 53", said(lab.signs))

    def test_thirty_one_rules_have_never_fired(self):
        dead = [finding for finding in self.roads.findings if finding.kind == "dead-rule"]
        self.assertEqual(len(dead[0].rules), 31)

    def test_what_we_did_not_read_is_named(self):
        self.assertTrue(any("connection-nat-state" in note for note in said(self.roads.notes)))
        self.assertTrue(any("raw" in note for note in said(self.roads.notes)))


if __name__ == "__main__":
    unittest.main()

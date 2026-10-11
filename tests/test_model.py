import unittest
from pathlib import Path

from lan_map.atlas import Atlas
from lan_map.model import NETMAP, PEER, Network, seconds, spell
from lan_map.snapshot import Snapshot

from .samples import HOME, LAB, SERVERS, address, lease, snapshot

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "snapshot.json"


class SegmentsTest(unittest.TestCase):
    def test_a_castle_per_network_except_the_one_facing_outside(self):
        net = Network.of(snapshot(**{
            "ip/address": [HOME, address("192.168.0.2/24", "ether5", "192.168.0.0", dynamic="true")],
            "interface/list/member": [{"list": "WAN", "interface": "ether5"}, {"list": "LAN", "interface": "bridge_main"}],
        }), Atlas.empty())
        self.assertEqual([segment.key for segment in net.segments], ["bridge_main"])
        self.assertEqual(net.segments[0].lists, ("LAN",))

    def test_vlan_and_a_castle_that_appears_with_the_vpn(self):
        net = Network.of(snapshot(**{
            "ip/address": [LAB, address("192.168.216.1/24", "back-to-home-vpn", "192.168.216.0", dynamic="true")],
            "interface/vlan": [{"name": "vlan20_lab", "vlan-id": "20", "interface": "bridge_main"}],
        }), Atlas.empty())
        lab, vpn = net.segments
        self.assertEqual((lab.vlan, lab.temporary), (20, False))
        self.assertEqual((vpn.vlan, vpn.temporary), (None, True))

    def test_the_atlas_names_castles_but_invents_nothing(self):
        tables = {"ip/address": [HOME]}
        plain = Network.of(snapshot(**tables), Atlas.empty()).segments[0]
        named = Network.of(snapshot(**tables), Atlas(segments={"bridge_main": {"title": "Home", "trusted": True}})).segments[0]
        self.assertEqual((plain.title, plain.trusted), ("bridge_main", False))
        self.assertEqual((named.title, named.trusted), ("Home", True))


class DevicesTest(unittest.TestCase):
    def test_a_device_is_found_by_lease_and_by_arp(self):
        net = Network.of(snapshot(**{
            "ip/address": [HOME], "ip/dhcp-server": SERVERS,
            "ip/dhcp-server/lease": [lease("192.168.88.10", "home", "AA:BB:CC:00:00:01", "ноутбук")],
            "ip/arp": [{"address": "192.168.88.20", "interface": "bridge_main",
                        "mac-address": "AA:BB:CC:00:00:02", "complete": "true"}],
        }), Atlas.empty())
        self.assertEqual({device.name for device in net.devices}, {"ноутбук", ""})
        self.assertTrue(all(device.online for device in net.devices))

    def test_one_name_in_two_castles_is_one_device(self):
        net = Network.of(snapshot(**{
            "ip/address": [HOME, LAB], "ip/dhcp-server": SERVERS,
            "ip/dhcp-server/lease": [lease("192.168.88.200", "home", "AA:BB:CC:00:00:10", "nas"),
                                     lease("192.168.20.30", "lab", "AA:BB:CC:00:00:11", "nas")],
        }), Atlas.empty())
        self.assertEqual(len(net.devices), 1)
        device = net.devices[0]
        self.assertTrue(device.in_two_castles)
        self.assertEqual(sorted(seat.ip for seat in device.seats), ["192.168.20.30", "192.168.88.200"])

    def test_the_same_name_twice_in_one_castle_is_two_devices(self):
        net = Network.of(snapshot(**{
            "ip/address": [HOME, LAB], "ip/dhcp-server": SERVERS,
            "ip/dhcp-server/lease": [lease("192.168.88.60", "home", "AA:BB:CC:00:00:20", "iPhone"),
                                     lease("192.168.88.61", "home", "AA:BB:CC:00:00:21", "iPhone"),
                                     lease("192.168.20.61", "lab", "AA:BB:CC:00:00:22", "iPhone")],
        }), Atlas.empty())
        self.assertEqual(len(net.devices), 3)
        self.assertFalse(any(device.in_two_castles for device in net.devices))

    def test_an_old_lease_is_not_a_second_home(self):
        """The phone moved to the guests: its address is known in two networks, it lives in one."""
        net = Network.of(snapshot(**{
            "ip/address": [HOME, LAB], "ip/dhcp-server": SERVERS,
            "ip/dhcp-server/lease": [lease("192.168.88.3", "home", "AA:BB:CC:00:00:30", "телефон", status="waiting"),
                                     lease("192.168.20.3", "lab", "AA:BB:CC:00:00:31", "телефон")],
        }), Atlas.empty())
        device = net.devices[0]
        self.assertEqual(len(device.segments), 2)
        self.assertEqual(device.homes, ("vlan20_lab",))
        self.assertFalse(device.in_two_castles)

    def test_a_stale_arp_record_is_not_a_second_home(self):
        """The device moved: in the old castle the router remembers it, but is no longer sure."""
        net = Network.of(snapshot(**{
            "ip/address": [HOME, LAB], "ip/dhcp-server": SERVERS,
            "ip/dhcp-server/lease": [lease("192.168.20.40", "lab", "AA:BB:CC:00:00:60", "home assistant")],
            "ip/arp": [{"address": "192.168.88.8", "interface": "bridge_main", "status": "stale",
                        "mac-address": "AA:BB:CC:00:00:60", "complete": "true"}],
        }), Atlas.empty())
        device = net.devices[0]
        self.assertEqual(device.homes, ("vlan20_lab",))
        self.assertFalse(device.in_two_castles)

    def test_a_stale_record_alone_is_not_proof_that_the_device_is_here(self):
        """The router saw it once and has not asked since. That is a memory, not a resident."""
        net = Network.of(snapshot(**{
            "ip/address": [HOME],
            "ip/arp": [{"address": "192.168.88.30", "interface": "bridge_main", "status": "stale",
                        "mac-address": "AA:BB:CC:00:00:61", "complete": "true"}],
        }), Atlas.empty())
        self.assertFalse(net.devices[0].online)

    def test_the_wifi_list_vouches_for_a_stale_record(self):
        """The device is silent but holds on to the air: so it is here."""
        net = Network.of(snapshot(**{
            "ip/address": [HOME],
            "ip/arp": [{"address": "192.168.88.30", "interface": "bridge_main", "status": "stale",
                        "mac-address": "AA:BB:CC:00:00:61", "complete": "true"}],
            "interface/wifi/registration-table": [{"mac-address": "AA:BB:CC:00:00:61"}],
        }), Atlas.empty())
        self.assertTrue(net.devices[0].online)

    def test_a_place_remembers_when_it_was_last_seen(self):
        """A castle counts those who are away too: they are the ones asked about, "when was it here?"."""
        net = Network.of(snapshot(**{
            "ip/address": [HOME], "ip/dhcp-server": SERVERS,
            "ip/dhcp-server/lease": [lease("192.168.88.11", "home", "AA:BB:CC:00:00:70", "ноутбук",
                                           status="waiting", last="3h20m")],
        }), Atlas.empty())
        seat = net.devices[0].seats[0]
        self.assertFalse(seat.online)
        self.assertEqual(seat.last, "3h20m")

    def test_an_unanswered_arp_record_is_not_a_dweller(self):
        """The router asked "who is at this address" and heard nothing. That is no dweller."""
        net = Network.of(snapshot(**{
            "ip/address": [HOME],
            "ip/arp": [{"address": "192.168.88.40", "interface": "bridge_main", "status": "failed"},
                       {"address": "192.168.88.41", "interface": "bridge_main", "status": "reachable",
                        "mac-address": "AA:BB:CC:00:00:80", "complete": "true"}],
        }), Atlas.empty())
        self.assertEqual([seat.ip for device in net.devices for seat in device.seats], ["192.168.88.41"])

    def test_the_atlas_gives_a_name_and_a_kind(self):
        tables = {"ip/address": [LAB], "ip/dhcp-server": SERVERS,
                  "ip/dhcp-server/lease": [lease("192.168.20.20", "lab", "AA:BB:CC:00:00:40")]}
        atlas = Atlas(devices={"192.168.20.20": {"name": "box", "kind": "server"}})
        device = Network.of(snapshot(**tables), atlas).devices[0]
        self.assertEqual((device.name, device.kind), ("box", "server"))
        self.assertEqual(Network.of(snapshot(**tables), Atlas.empty()).devices[0].name, "")

    def test_the_atlas_can_join_two_addresses_by_hand(self):
        tables = {"ip/address": [HOME, LAB], "ip/dhcp-server": SERVERS,
                  "ip/dhcp-server/lease": [lease("192.168.88.7", "home", "AA:BB:CC:00:00:50"),
                                           lease("192.168.20.7", "lab", "AA:BB:CC:00:00:51")]}
        self.assertEqual(len(Network.of(snapshot(**tables), Atlas.empty()).devices), 2)
        joined = Network.of(snapshot(**tables), Atlas(same=(("192.168.88.7", "192.168.20.7"),))).devices
        self.assertEqual(len(joined), 1)
        self.assertTrue(joined[0].in_two_castles)

    def test_a_missing_wifi_table_is_said_out_loud(self):
        bare = snapshot(**{"ip/address": [HOME]})
        without = Snapshot(bare.taken, {k: v for k, v in bare.tables.items() if k != "interface/wifi/registration-table"},
                           {"interface/wifi/registration-table": "the router did not answer"})
        net = Network.of(without, Atlas.empty())
        self.assertTrue(any(puzzle.key == "puzzle.no-wifi" for puzzle in net.puzzles))


class OutpostTest(unittest.TestCase):
    """Beyond the gate may lie not the internet but another private network: seen, not ours."""

    WAN = [{"list": "WAN", "interface": "ether5"}, {"list": "LAN", "interface": "bridge_main"}]

    def test_a_private_network_behind_the_gate_is_seen(self):
        net = Network.of(snapshot(**{
            "ip/address": [HOME, address("192.168.0.2/24", "ether5", "192.168.0.0", dynamic="true")],
            "interface/list/member": self.WAN,
            "ip/arp": [{"address": "192.168.0.1", "interface": "ether5", "status": "reachable",
                        "mac-address": "02:00:00:00:01:01", "complete": "true"}],
            "ip/route": [{"dst-address": "0.0.0.0/0", "gateway": "192.168.0.1"}],
        }), Atlas.empty())
        post = net.outpost
        self.assertEqual((post.network, post.ours, post.gate),
                         ("192.168.0.0/24", "192.168.0.2", "192.168.0.1"))
        self.assertEqual(post.neighbours, (("192.168.0.1", "02:00:00:00:01:01"),))

    def test_the_neighbour_behind_the_gate_is_not_a_dweller(self):
        """A neighbour on the provider's side does not move into a castle: not our network."""
        net = Network.of(snapshot(**{
            "ip/address": [HOME, address("192.168.0.2/24", "ether5", "192.168.0.0", dynamic="true")],
            "interface/list/member": self.WAN,
            "ip/arp": [{"address": "192.168.0.1", "interface": "ether5", "status": "reachable",
                        "mac-address": "02:00:00:00:01:01", "complete": "true"}],
        }), Atlas.empty())
        self.assertEqual(net.devices, ())
        self.assertEqual([segment.key for segment in net.segments], ["bridge_main"])

    def test_a_real_internet_address_means_there_is_no_outpost(self):
        net = Network.of(snapshot(**{
            "ip/address": [HOME, address("95.24.13.7/24", "ether5", "95.24.13.0", dynamic="true")],
            "interface/list/member": self.WAN,
        }), Atlas.empty())
        self.assertIsNone(net.outpost)

    def test_without_a_route_table_we_do_not_name_the_gate(self):
        """The gateway is not guessed: an ARP neighbour and who is in charge are different things."""
        net = Network.of(snapshot(**{
            "ip/address": [HOME, address("192.168.0.2/24", "ether5", "192.168.0.0", dynamic="true")],
            "interface/list/member": self.WAN,
        }), Atlas.empty())
        self.assertEqual(net.outpost.gate, "")


class RealSnapshotTest(unittest.TestCase):
    """The sample came from a real network: it shows what no test could invent."""

    def setUp(self):
        self.net = Network.of(Snapshot.read(FIXTURE), Atlas.empty())

    def test_five_castles_and_one_of_them_appears_with_the_vpn(self):
        self.assertEqual(len(self.net.segments), 5)
        vpn = [segment for segment in self.net.segments if segment.temporary]
        self.assertEqual([segment.network for segment in vpn], ["192.168.216.0/24"])
        self.assertIn("LAN", vpn[0].lists)

    def test_only_the_nas_lives_in_two_castles(self):
        doubles = [device for device in self.net.devices if device.in_two_castles]
        self.assertEqual(len(doubles), 1)
        self.assertEqual(sorted(doubles[0].homes), ["bridge_main", "vlan20_lab"])

    def test_nothing_is_left_unexplained(self):
        self.assertEqual(self.net.puzzles, ())

    def test_devices_without_a_name_are_counted_not_invented(self):
        """Twelve, not nineteen: seven ARP records went unanswered and became no dwellers."""
        unnamed = [device for device in self.net.devices if not device.name]
        self.assertEqual(len(unnamed), 12)
        self.assertTrue(all(device.name == "" for device in unnamed))


class WireguardTest(unittest.TestCase):
    """A phone on the VPN: the router knows it as a peer and in no other way at all."""

    def net(self, *peers):
        taken = snapshot(**{"ip/address": [HOME, address("192.168.216.1/24", "wg",
                                                         "192.168.216.0", dynamic="true")],
                            "interface/wireguard/peers": list(peers)})
        return Network.of(taken, Atlas.empty())

    def peer(self, ip="192.168.216.3/32", comment="wg iPhone", shook="00:00:16", **fields):
        return {"interface": "wg", "allowed-address": ip, "comment": comment,
                "last-handshake": shook, **fields}

    def test_a_peer_is_a_device_in_the_network_of_its_own_address(self):
        devices = self.net(self.peer()).devices
        self.assertEqual([one.name for one in devices], ["iPhone"])
        seat = devices[0].seats[0]
        self.assertEqual((seat.ip, seat.segment, seat.online, seat.seen),
                         ("192.168.216.3", "wg", True, (PEER,)))

    def test_a_peer_with_no_name_of_its_own_is_left_nameless(self):
        """Back to Home writes the interface as the whole comment when nobody named the peer.
        Calling the device after the tunnel it sits in tells the reader nothing."""
        self.assertEqual(self.net(self.peer(comment="wg")).devices[0].name, "")

    def test_a_peer_that_has_gone_quiet_is_not_online(self):
        """WireGuard speaks every couple of minutes while it carries anything. An hour of
        silence is a tunnel standing open, which is not somebody being there."""
        seat = self.net(self.peer(shook="01:00:00")).devices[0].seats[0]
        self.assertFalse(seat.online)
        self.assertEqual(seat.last, "1h")

    def test_a_peer_that_never_shook_hands_is_not_online_and_says_nothing(self):
        seat = self.net(self.peer(shook="")).devices[0].seats[0]
        self.assertFalse(seat.online)
        self.assertEqual(seat.last, "")

    def test_a_peer_allowed_a_whole_network_is_nobody_in_particular(self):
        """That is a road to whatever stands behind it, not a device with an address."""
        self.assertEqual(self.net(self.peer(ip="192.168.220.0/24")).devices, ())

    def test_a_disabled_peer_is_not_there(self):
        self.assertEqual(self.net(self.peer(disabled="true")).devices, ())

    def test_without_the_menu_the_map_says_nothing_about_peers(self):
        """An old RouterOS, or one built without WireGuard: not a fault, and not emptiness."""
        taken = snapshot(**{"ip/address": [HOME]})
        without = Snapshot(taken.taken,
                           {key: value for key, value in taken.tables.items()
                            if key != "interface/wireguard/peers"},
                           {"interface/wireguard/peers": {"key": "router.no-menu"}})
        self.assertEqual(Network.of(without, Atlas.empty()).devices, ())


class NetmapTest(unittest.TestCase):
    """What the router shows an address as: the device stands where it lives and where it is seen."""

    RULE = {"chain": "srcnat", "action": "netmap", "in-interface": "wg",
            "to-addresses": "192.168.100.0/24", "out-interface": "!wg"}

    def net(self, *rules, peer="192.168.216.3/32"):
        taken = snapshot(**{
            "ip/address": [HOME,
                           address("192.168.216.1/24", "wg", "192.168.216.0", dynamic="true"),
                           address("192.168.100.1/24", "vlan100", "192.168.100.0")],
            "interface/wireguard/peers": [{"interface": "wg", "allowed-address": peer,
                                           "comment": "wg iPhone", "last-handshake": "00:00:16"}],
            "ip/firewall/nat": list(rules)})
        return Network.of(taken, Atlas.empty())

    def test_a_netmapped_device_stands_in_both_networks(self):
        device = self.net(self.RULE).devices[0]
        self.assertEqual([(seat.ip, seat.segment, seat.seen) for seat in device.seats],
                         [("192.168.216.3", "wg", (PEER,)),
                          ("192.168.100.3", "vlan100", (NETMAP,))])
        self.assertTrue(device.in_two_castles)

    def test_without_the_rule_it_stands_in_one(self):
        self.assertEqual([seat.ip for seat in self.net().devices[0].seats], ["192.168.216.3"])

    def test_a_rule_that_is_off_shows_nothing(self):
        off = {**self.RULE, "disabled": "true"}
        self.assertEqual([seat.ip for seat in self.net(off).devices[0].seats], ["192.168.216.3"])

    def test_a_rule_about_another_interface_shows_nothing(self):
        other = {**self.RULE, "in-interface": "bridge_main"}
        self.assertEqual([seat.ip for seat in self.net(other).devices[0].seats],
                         ["192.168.216.3"])

    def test_a_rule_picking_its_traffic_by_a_list_is_left_alone(self):
        """It may or may not touch this address; a map that guesses is worse than a quiet one."""
        by_list = {key: value for key, value in self.RULE.items() if key != "in-interface"}
        by_list["in-interface-list"] = "SEGMENTS"
        self.assertEqual([seat.ip for seat in self.net(by_list).devices[0].seats],
                         ["192.168.216.3"])

    def test_ranges_of_different_sizes_are_not_guessed_at(self):
        odd = {**self.RULE, "to-addresses": "192.168.100.0/25"}
        self.assertEqual([seat.ip for seat in self.net(odd).devices[0].seats],
                         ["192.168.216.3"])


class SpansTest(unittest.TestCase):
    def test_the_router_writes_a_span_two_ways_and_both_are_read(self):
        self.assertEqual(seconds("00:00:16"), 16)
        self.assertEqual(seconds("1w2d03:04:05"), 788645)
        self.assertEqual(seconds("22w20h31m31s"), 13379491)
        self.assertIsNone(seconds(""))

    def test_a_span_is_written_back_the_one_way_the_map_writes_them(self):
        self.assertEqual(spell(16), "16s")
        self.assertEqual(spell(3661), "1h1m")
        self.assertEqual(spell(0), "0s")
        self.assertEqual(spell(None), "")


if __name__ == "__main__":
    unittest.main()

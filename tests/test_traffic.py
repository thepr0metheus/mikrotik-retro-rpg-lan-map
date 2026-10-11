import unittest

from lan_map.atlas import Atlas
from lan_map.memory import Memory
from lan_map.model import Network
from lan_map.roads import INTERNET, ROUTER, SHOUT
from lan_map.snapshot import Snapshot
from lan_map.traffic import Traffic

from .samples import HOME, LAB, MEMBERS, address, snapshot

TUNNEL = address("192.168.216.1/24", "back-to-home-vpn", "192.168.216.0")


def link(source, target, protocol="tcp"):
    return {"src-address": f"{source}:51234", "dst-address": f"{target}:443", "protocol": protocol}


def walking(*links, cache=(), peers=()) -> Traffic:
    taken = snapshot(**{"ip/address": [HOME, LAB, TUNNEL], "interface/list/member": MEMBERS,
                        "ip/firewall/connection": list(links), "ip/dns/cache": list(cache),
                        "interface/wireguard/peers": list(peers)})
    return Traffic.of(taken, Network.of(taken, Atlas.empty()))


def peer(ip, handshake):
    return {"interface": "back-to-home-vpn", "allowed-address": f"{ip}/32",
            "last-handshake": handshake, "disabled": "false"}


def cached(name, data, kind="A"):
    return {"name": name, "data": data, "type": kind, "ttl": "00:04:33"}


class TrafficTest(unittest.TestCase):
    def test_who_walks_between_castles(self):
        traffic = walking(link("192.168.20.10", "192.168.88.200"),
                          link("192.168.20.11", "192.168.88.200"))
        self.assertEqual(traffic.counts, {("vlan20_lab", "bridge_main"): 2})

    def test_a_walk_outside_is_a_walk_to_the_sea(self):
        traffic = walking(link("192.168.88.10", "142.250.74.14"))
        self.assertEqual(traffic.counts, {("bridge_main", INTERNET): 1})

    def test_talking_to_the_router_is_not_walking_into_his_network(self):
        """192.168.88.1 lies inside 192.168.88.0/24, so by range alone the router would pass
        for a dweller of Home, and a conversation with him would be drawn as a journey there."""
        traffic = walking(link("192.168.20.10", "192.168.88.1"))
        self.assertEqual(traffic.counts, {("vlan20_lab", ROUTER): 1})

    def test_the_router_speaking_out_starts_at_the_customs_house(self):
        traffic = walking(link("192.168.88.1", "216.239.35.4"))
        self.assertEqual(traffic.counts, {(ROUTER, INTERNET): 1})

    def test_a_castle_talking_to_its_own_gateway_still_leaves_the_castle(self):
        """Home to 192.168.88.1 is a walk out of Home, not a walk inside it: the two ends differ."""
        traffic = walking(link("192.168.88.10", "192.168.88.1"))
        self.assertEqual(traffic.counts, {("bridge_main", ROUTER): 1})

    def test_inside_one_castle_the_router_sees_nothing(self):
        """Neighbour calls neighbour past the router. What he never saw, the map will not show."""
        self.assertEqual(walking(link("192.168.88.10", "192.168.88.11")).counts, {})

    def test_a_device_that_left_walks_nowhere(self):
        """
        The router keeps an established TCP connection for a day after its last packet. A phone
        whose tunnel went quiet an hour ago cannot send a thing — WireGuard carries nothing
        without a fresh handshake — yet its connections are all still in the table.
        """
        traffic = walking(link("192.168.216.3", "149.154.167.223"),
                          link("192.168.216.3", "149.154.166.111"),
                          link("192.168.216.4", "142.250.74.14"),
                          peers=[peer("192.168.216.3", "51m18s"), peer("192.168.216.4", "1m30s")])
        self.assertEqual(traffic.counts, {("back-to-home-vpn", INTERNET): 1})
        self.assertEqual(set(traffic.trips), {"192.168.216.4"})

    def test_nobody_walks_to_a_device_that_left_either(self):
        traffic = walking(link("192.168.20.10", "192.168.216.3"),
                          peers=[peer("192.168.216.3", "51m18s")])
        self.assertEqual(traffic.counts, {})

    def test_an_address_the_map_never_saw_still_walks(self):
        """Unknown is not gone. Only a known absence silences a connection."""
        traffic = walking(link("192.168.20.77", "142.250.74.14"),
                          peers=[peer("192.168.216.3", "51m18s")])
        self.assertEqual(traffic.counts, {("vlan20_lab", INTERNET): 1})

    def test_an_address_we_could_not_read_is_skipped(self):
        self.assertEqual(walking({"src-address": "почта", "dst-address": "192.168.88.200:443"}).counts, {})

    def test_a_table_that_was_not_taken_is_said_out_loud(self):
        bare = snapshot(**{"ip/address": [HOME]})
        without = Snapshot(bare.taken, {key: value for key, value in bare.tables.items()
                                        if key != Traffic.TABLE}, {})
        traffic = Traffic.of(without, Network.of(without, Atlas.empty()))
        self.assertEqual(traffic.missing.key, "traffic.not-taken")
        self.assertEqual(traffic.counts, {})

    def test_the_road_says_who_rides_it(self):
        """A cart needs a rider: it carries the icon of whoever really walks the road."""
        traffic = walking(link("192.168.20.10", "192.168.88.200"),
                          link("192.168.20.10", "192.168.88.201"),
                          link("192.168.20.11", "192.168.88.200"))
        who = traffic.rows()[0]["who"]
        self.assertEqual([one["ip"] for one in who], ["192.168.20.10", "192.168.20.11"])
        self.assertEqual([one["count"] for one in who], [2, 1])

    def test_a_walk_remembers_which_road_it_belongs_to(self):
        """A cart's caption asks "what do you carry on this road": the answer is matched by
        the road's key, so the walk has to know it. Working the castle out from the address
        a second time, in the page, would be the same answer at twice the price."""
        traffic = walking(link("192.168.20.10", "192.168.88.1"),
                          link("192.168.20.10", "192.168.88.200"),
                          link("192.168.20.10", "8.8.8.8"))
        walks = {walk["to"]: walk["where"] for walk in traffic.walks("192.168.20.10")}
        self.assertEqual(walks, {"192.168.88.1": ROUTER, "192.168.88.200": "bridge_main",
                                 "8.8.8.8": INTERNET})

    def test_a_walk_inside_ones_own_castle_is_still_a_walk(self):
        """The road ends where it started: the router saw it, so the scroll may show it."""
        traffic = walking(link("192.168.88.10", "192.168.88.11"))
        self.assertEqual([walk["where"] for walk in traffic.walks("192.168.88.10")],
                         ["bridge_main"])

    def test_a_walk_is_named_by_what_the_router_himself_resolved(self):
        """He looked the name up for somebody on this very network: the map only reads it back."""
        traffic = walking(link("192.168.88.10", "17.248.213.65"),
                          cache=[cached("gateway.icloud.com", "17.248.213.65")])
        self.assertEqual([walk["name"] for walk in traffic.walks("192.168.88.10")],
                         ["gateway.icloud.com"])

    def test_of_many_names_at_one_address_the_shortest_is_taken(self):
        """A reader knows push.apple.com; use1-pp-st-vs-sc.push.apple.com only makes him squint."""
        traffic = walking(link("192.168.88.10", "17.248.213.65"),
                          cache=[cached("use1-pp-st-vs-sc.push.apple.com", "17.248.213.65"),
                                 cached("push.apple.com", "17.248.213.65")])
        self.assertEqual(traffic.names["17.248.213.65"], "push.apple.com")

    def test_a_name_that_answers_with_another_name_is_no_address(self):
        """A CNAME holds a name in its data, not an address: taken for one it would name nobody."""
        traffic = walking(link("192.168.88.10", "17.248.213.65"),
                          cache=[cached("push.apple.com", "17.courier.apple.com.akadns.net.",
                                        kind="CNAME")])
        self.assertEqual(traffic.names, {})

    def test_without_the_cache_an_address_stays_a_number(self):
        """A router that keeps no cache is not a fault: the map says the address and no more."""
        taken = snapshot(**{"ip/address": [HOME, LAB], "interface/list/member": MEMBERS,
                            "ip/firewall/connection": [link("192.168.88.10", "8.8.8.8")]})
        without = Snapshot(taken.taken, {key: value for key, value in taken.tables.items()
                                         if key != Memory.CACHE},
                           {Memory.CACHE: {"key": "router.no-menu"}})
        traffic = Traffic.of(without, Network.of(without, Atlas.empty()))
        self.assertEqual(traffic.names, {})
        self.assertEqual([walk["name"] for walk in traffic.walks("192.168.88.10")], [""])

    def test_a_shout_to_everybody_is_no_journey(self):
        """255.255.255.255 is not a place in the sea, and a cart sent there meets nobody."""
        traffic = walking(link("192.168.88.10", "255.255.255.255"))
        self.assertEqual(traffic.counts, {})

    def test_a_shout_to_a_crowd_is_no_journey_either(self):
        """224.0.0.251 is mdns asking the whole yard at once — no castle stands at that address."""
        self.assertEqual(walking(link("192.168.88.10", "224.0.0.251", "udp")).counts, {})

    def test_a_shout_is_still_a_walk_and_is_shown_as_one(self):
        """The router saw it, and next to the one who shouts it is worth reading. It only has
        no road: the walk is marked as belonging to nobody, so no cart can pick it up."""
        traffic = walking(link("192.168.88.10", "224.0.0.251", "udp"))
        walks = traffic.walks("192.168.88.10")
        self.assertEqual([(walk["to"], walk["where"]) for walk in walks],
                         [("224.0.0.251", SHOUT)])

    def test_the_sea_is_still_the_sea(self):
        """The shout must not swallow ordinary addresses on its way past."""
        self.assertEqual(walking(link("192.168.88.10", "223.255.255.255")).counts,
                         {("bridge_main", INTERNET): 1})

    def test_the_busiest_road_comes_first(self):
        traffic = walking(link("192.168.20.10", "192.168.88.200"),
                          link("192.168.20.11", "192.168.88.200"),
                          link("192.168.88.10", "8.8.8.8"))
        self.assertEqual([row["count"] for row in traffic.rows()], [2, 1])


if __name__ == "__main__":
    unittest.main()

import unittest

from lan_map.atlas import Atlas
from lan_map.model import Network
from lan_map.names import Names, Record
from lan_map.snapshot import Snapshot

from .samples import HOME, LAB, MEMBERS, SERVERS, lease, snapshot

NAS = "192.168.20.10"


def record(name, answer="", kind="A", **fields):
    """A static record as the router's REST gives it: every value a string."""
    row = {"name": name, "type": kind, "ttl": "5m", "comment": "", "disabled": "false"}
    if answer:
        row[Record.ANSWERS[kind]] = answer
    row.update({key.replace("_", "-"): value for key, value in fields.items()})
    return row


def network(address, dns=""):
    return {"address": address, "dns-server": dns}


class NamesTest(unittest.TestCase):
    def names(self, records=(), networks=()) -> Names:
        taken = snapshot(**{
            "ip/address": [HOME, LAB], "interface/list/member": MEMBERS, "ip/dhcp-server": SERVERS,
            "ip/dhcp-server/lease": [lease(NAS, "lab", "AA:00:00:00:00:10", "nas01")],
            "ip/dns/static": list(records), "ip/dhcp-server/network": list(networks)})
        return Names.of(taken, Network.of(taken, Atlas.empty()))

    # --- where a name leads ----------------------------------------------------------------------
    def test_a_name_leads_to_the_device_that_holds_its_address(self):
        place, = self.names([record("lan.example", NAS), record("git.lan.example", NAS)]).places
        self.assertEqual((place.where, place.who, place.to, place.segment),
                         ("device", "nas01", NAS, "vlan20_lab"))
        self.assertEqual([one.name for one in place.records], ["git.lan.example", "lan.example"])

    def test_the_routers_own_address_is_the_router(self):
        place, = self.names([record("router.lan", "192.168.88.1")]).places
        self.assertEqual((place.where, place.who, place.segment), ("router", "", "bridge_main"))

    def test_an_address_nobody_holds_is_said_to_be_held_by_nobody(self):
        """The device may be off, or gone and its name left behind: either way it is shown."""
        places = self.names([record("old.lan.example", "192.168.88.200"),
                             record("far.lan.example", "10.9.9.9")]).places
        stale, outside = (next(place for place in places if place.to == to)
                          for to in ("192.168.88.200", "10.9.9.9"))
        self.assertEqual((stale.where, stale.segment), ("nobody", "bridge_main"))
        self.assertEqual((outside.where, outside.segment), ("nobody", ""))

    def test_the_answer_with_the_most_names_comes_first(self):
        places = self.names([record("router.lan", "192.168.88.1"),
                             record("a.lan.example", NAS), record("b.lan.example", NAS)]).places
        self.assertEqual([place.to for place in places], [NAS, "192.168.88.1"])

    def test_a_name_that_is_not_an_address_leads_to_no_house(self):
        """A CNAME whose target looks like an address is still a name, not a house."""
        place, = self.names([record("files.lan.example", NAS, kind="CNAME")]).places
        self.assertEqual((place.where, place.to, place.who, place.segment), ("beyond", NAS, "", ""))

    # --- what the router says of a record --------------------------------------------------------
    def test_a_record_carries_its_marks(self):
        self.assertEqual(Record.of(record("x.lan", NAS, disabled="true")).disabled, True)
        self.assertEqual(Record.of(record("x.lan", NAS, match_subdomain="true")).subdomains, True)
        pattern = Record.of({"regexp": ".*\\.test$", "address": NAS, "ttl": "1d"})
        self.assertEqual((pattern.name, pattern.pattern, pattern.kind), (".*\\.test$", True, "A"))

    def test_a_type_the_map_does_not_know_has_no_answer_rather_than_a_guessed_one(self):
        odd = Record.of({"name": "x.lan", "type": "SVCB", "address": NAS})
        self.assertEqual((odd.kind, odd.to, odd.leads_home), ("SVCB", "", False))

    # --- who asks the router ---------------------------------------------------------------------
    def test_a_network_handed_the_router_asks_the_router(self):
        home, lab, bare = self.names(networks=[network("192.168.88.0/24", "192.168.88.1"),
                                               network("192.168.20.0/24", "192.168.20.1,8.8.8.8"),
                                               network("192.168.99.0/24")]).askers
        self.assertEqual((home.segment, home.servers, home.router),
                         ("bridge_main", ("192.168.88.1",), True))
        self.assertEqual((lab.segment, lab.router), ("vlan20_lab", False))
        self.assertEqual((bare.segment, bare.servers, bare.router), ("", (), None))

    # --- nothing there ---------------------------------------------------------------------------
    def test_a_router_without_names_is_an_empty_list(self):
        self.assertEqual(self.names().places, ())

    def test_the_names_are_a_table_no_snapshot_goes_without(self):
        """So an empty list is the router's answer, never a table that failed to arrive."""
        self.assertIn(Names.TABLE, Snapshot.PATHS)
        self.assertNotIn(Names.TABLE, Snapshot.OPTIONAL)


if __name__ == "__main__":
    unittest.main()

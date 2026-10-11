"""DSM's own gate: reading its files, and telling them against the router's roads."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from lan_map.containers import Containers
from lan_map.gate import Door, Gate, GateReader, ProxyRules
from lan_map.model import Network, Segment
from lan_map.roads import Opening, Road, RuleRef, Roads
from lan_map.spans import ANY_PORT, Space
from lan_map.tongue import Tongue

#: The reverse proxy as DSM writes it, cut down to the cases that matter: one name on two ports,
#: a name with an access profile, a name led on to another machine, a block with nowhere to pass.
PROXY = """server {
    listen 80;
    listen [::]:80;
    server_name lan.example ;
    if ( $host !~ "(^lan.example$)" ) { return 404; }
    location / {
        proxy_set_header        Host            $http_host;
        proxy_pass http://127.0.0.1:18090;
    }
    error_page 403 404 500 502 503 504 /dsm_error_page;
    location /dsm_error_page {
        internal;
        root /usr/syno/share/nginx;
        allow all;
    }
}
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name lan.example ;
    location / {
        proxy_pass http://127.0.0.1:18090;
    }
}
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name vault.lan.example ;
    include /usr/syno/etc/www/certificate/ReverseProxy_f50e/cert.conf*;
    include conf.d/.acl.6499f021.conf*;
    location / {
        proxy_pass http://127.0.0.1:18100;
    }
}
server {
    listen 443 ssl;
    server_name caravan.lan.example ;
    location / {
        proxy_pass http://192.168.30.20:7990;
    }
}
server {
    listen 443 ssl;
    server_name nowhere.lan.example ;
    return 404;
}
"""
PROFILE = "\nallow 192.168.10.0/24;\n\nallow 192.168.88.0/24;\n\ndeny all;\n"
NOW = datetime(2026, 10, 4, 20, 0, tzinfo=timezone.utc)
NAS = "192.168.20.10"


class ProxyRulesTest(unittest.TestCase):
    def test_a_block_is_read_for_its_names_ports_target_and_profile(self):
        blocks = ProxyRules.blocks(PROXY)
        self.assertEqual([block["names"] for block in blocks],
                         [["lan.example"], ["lan.example"], ["vault.lan.example"], ["caravan.lan.example"]])
        vault = blocks[2]
        self.assertEqual((vault["ports"], vault["to"], vault["profile"]),
                         ([443], "http://127.0.0.1:18100", "conf.d/.acl.6499f021.conf"))

    def test_the_error_pages_allow_all_is_not_a_profile(self):
        """`allow all` inside the error page's location lets the error page be shown, nothing more."""
        self.assertEqual(ProxyRules.blocks(PROXY)[0]["profile"], "")

    def test_a_profile_is_read_in_its_own_order(self):
        self.assertEqual(ProxyRules.rules(PROFILE),
                         [["allow", "192.168.10.0/24"], ["allow", "192.168.88.0/24"], ["deny", "all"]])


class GateReaderTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        self.nginx, self.firewall = root / "nginx", root / "firewall.d"
        (self.nginx / "sites-enabled").mkdir(parents=True)
        (self.nginx / "conf.d").mkdir()
        self.firewall.mkdir()
        (self.nginx / ProxyRules.FILE).write_text(PROXY, encoding="utf-8")
        (self.nginx / "conf.d/.acl.6499f021.conf").write_text(PROFILE, encoding="utf-8")
        self.wall({"profile": "default", "status": False},
                  {"name": "default", "rules": None, "adapterPolicyMap": {"global": 2}},
                  {"name": "custom", "rules": [{"policy": 1}, {"policy": 0}]})
        self.reader = GateReader(self.nginx, self.firewall)

    def wall(self, settings, *profiles):
        (self.firewall / "firewall_settings.json").write_text(json.dumps(settings), encoding="utf-8")
        for number, profile in enumerate(profiles, start=1):
            (self.firewall / f"{number}.json").write_text(json.dumps(profile), encoding="utf-8")

    def test_every_name_is_one_door_and_one_name_on_two_ports_is_one(self):
        read = self.reader.read()
        self.assertEqual(read["missing"], "")
        self.assertEqual([(door["name"], door["ports"]) for door in read["doors"]],
                         [("caravan.lan.example", [443]), ("lan.example", [80, 443]),
                          ("vault.lan.example", [443])])
        vault = read["doors"][2]
        self.assertEqual(vault["profile"], ProxyRules.rules(PROFILE))
        self.assertIsNone(read["doors"][0]["profile"])

    def test_the_firewall_says_whether_it_is_on_and_how_many_rules_its_profile_holds(self):
        self.assertEqual(self.reader.read()["firewall"], {"missing": "", "on": False, "profile": "default", "rules": 0})
        self.wall({"profile": "custom", "status": True})
        self.assertEqual(self.reader.read()["firewall"], {"missing": "", "on": True, "profile": "custom", "rules": 2})

    def test_a_profile_that_will_not_open_is_unread_never_everyone(self):
        (self.nginx / "conf.d/.acl.6499f021.conf").unlink()
        vault = self.reader.read()["doors"][2]
        self.assertEqual(vault["profile"], GateReader.UNREAD)

    def test_what_is_not_there_is_named(self):
        self.assertEqual(GateReader(self.nginx / "gone", self.firewall / "gone").read(),
                         {"missing": "gate.not-mounted", "doors": [],
                          "firewall": {"missing": "gate.firewall-not-mounted"}})
        (self.nginx / ProxyRules.FILE).unlink()
        self.assertEqual(self.reader.read()["missing"], "gate.no-proxy")


def door(name, to, profile=None, ports=(443,)):
    return Door(name, ports, to, profile)


class DoorTest(unittest.TestCase):
    GUESTS = Space.addresses("192.168.10.0/24")

    def test_no_profile_lets_in_whoever_arrives(self):
        self.assertEqual(door("a", "http://127.0.0.1:1").admitted(self.GUESTS), self.GUESTS)

    def test_the_first_line_that_matches_decides(self):
        vault = door("vault", "http://127.0.0.1:18100", (("deny", "192.168.10.5"), ("allow", "192.168.10.0/24"),
                                                          ("deny", "all")))
        self.assertEqual(vault.admitted(self.GUESTS), self.GUESTS - Space.addresses("192.168.10.5"))
        self.assertEqual(vault.admitted(Space.addresses("192.168.20.0/24")), Space())

    def test_an_address_no_line_matches_is_let_in(self):
        self.assertEqual(door("a", "x", (("deny", "192.168.10.0/25"),)).admitted(self.GUESTS),
                         Space.addresses("192.168.10.128-192.168.10.255"))

    def test_an_ipv6_or_socket_line_cannot_touch_an_ipv4_network(self):
        self.assertEqual(door("a", "x", (("deny", "fe80::/10"), ("deny", "unix:"))).admitted(self.GUESTS), self.GUESTS)

    def test_a_line_the_map_cannot_read_makes_the_answer_unread(self):
        self.assertIsNone(door("a", "x", (("allow", "example.com"),)).admitted(self.GUESTS))
        self.assertIsNone(door("a", "x", "unread").admitted(self.GUESTS))

    def test_where_a_name_leads_and_whether_it_stays_on_the_nas(self):
        self.assertEqual(door("a", "https://localhost:5001").backend, ("localhost", 5001))
        self.assertEqual(door("a", "http://192.168.30.20").backend, ("192.168.30.20", 80))
        self.assertTrue(door("a", "http://localhost:8080").local(NAS))
        self.assertTrue(door("a", f"http://{NAS}:8080").local(NAS))
        self.assertFalse(door("a", "http://192.168.30.20:7990").local(NAS))


def segment(key, network):
    return Segment(key, key, network, network.replace("0/24", "1"), None, False, False, ())


def opening(source, target, protocol="any", ports=ANY_PORT):
    return Opening(source, target, protocol, ports, False, (), Space.addresses(source).spans,
                   Space.addresses(target).spans)


class GateTest(unittest.TestCase):
    """Guests reach the whole NAS network; the NAS reaches caravan in the lab on 7990 only; the UPS
    reaches the chat on the NAS and nothing else. Nothing leads from the guests into the lab."""

    def setUp(self):
        self.network = Network("taken", (segment("guests", "192.168.10.0/24"), segment("nas", "192.168.20.0/24"),
                                         segment("lab", "192.168.30.0/24"), segment("ups", "192.168.40.0/24")),
                               (), ())
        self.roads = Roads("taken", (
            Road("guests", "nas", "all", (opening("192.168.10.0/24", "192.168.20.0/24"),)),
            Road("nas", "lab", "ports", (opening("192.168.20.0/24", "192.168.30.20", "tcp", "7990"),)),
            Road("ups", "nas", "ports", (opening("192.168.40.0/24", NAS, "tcp", "8065"),)),
            Road("guests", "lab", "shut"),
        ))
        self.doors = [{"name": "vault.lan.example", "ports": [443], "to": "http://127.0.0.1:18100",
                       "profile": [["allow", "192.168.10.0/24"], ["deny", "all"]]},
                      {"name": "caravan.lan.example", "ports": [443], "to": "http://192.168.30.20:7990",
                       "profile": None},
                      {"name": "ha.lan.example", "ports": [443], "to": "http://192.168.20.40:8123", "profile": None}]

    def told(self, doors=None, here=NAS, roads=None, firewall=None) -> dict:
        written = {"taken": "2026-10-04T19:50:00+00:00", "every": 3600,
                   "gate": {"missing": "", "doors": self.doors if doors is None else doors,
                            "firewall": firewall or {"missing": "", "on": False, "profile": "default", "rules": 0}}}
        gate = Gate.of(Containers(written, NOW), self.network, roads or self.roads, here)
        return {one["name"]: one for one in gate.payload(Tongue.of("en"))["doors"]}

    def test_dsm_turns_away_only_those_the_router_lets_reach_the_nas(self):
        """The NAS's own network arrives without the router and is turned away; the UPS never
        gets as far as port 443, so the profile has nothing to say to it."""
        vault = self.told()["vault.lan.example"]
        self.assertEqual(vault["refuses"], [{"segment": "nas", "whole": True, "space": "192.168.20.0/24"}])
        self.assertEqual(vault["past"], [])

    def test_a_name_led_on_to_another_machine_is_a_way_past_the_router(self):
        caravan = self.told()["caravan.lan.example"]
        self.assertEqual((caravan["local"], caravan["beyond"], caravan["to"]), (False, "lab", "192.168.30.20:7990"))
        self.assertEqual(caravan["past"], [{"segment": "guests", "whole": True, "space": "192.168.10.0/24"}])

    def test_a_machine_the_guests_reach_anyway_is_no_way_past_anything(self):
        self.assertEqual(self.told()["ha.lan.example"]["past"], [])

    def test_a_name_the_nas_itself_cannot_reach_leads_nobody_anywhere(self):
        roads = Roads("taken", tuple(road for road in self.roads.roads if road.source != "nas"))
        self.assertEqual(self.told(roads=roads)["caravan.lan.example"]["past"], [])

    def test_a_profile_turns_away_part_of_a_network_by_its_addresses(self):
        doors = [{"name": "half", "ports": [443], "to": "http://127.0.0.1:1",
                  "profile": [["deny", "192.168.10.0/25"]]}]
        self.assertEqual(self.told(doors)["half"]["refuses"],
                         [{"segment": "guests", "whole": False, "space": "192.168.10.0-192.168.10.127"}])

    def test_an_unread_rule_on_the_way_is_unclear_not_open(self):
        puzzled = Roads("taken", (Road("guests", "nas", "puzzle", puzzles=(RuleRef(9, "accept", "?", 1),)),
                                  *self.roads.roads[1:]))
        vault = self.told(roads=puzzled)["vault.lan.example"]
        self.assertEqual((vault["refuses"], vault["unclear"]), ([{"segment": "nas", "whole": True,
                                                                 "space": "192.168.20.0/24"}], ["guests"]))

    def test_without_its_own_address_the_map_tells_the_names_and_judges_nothing(self):
        vault = self.told(here="")["vault.lan.example"]
        self.assertEqual((vault["refuses"], vault["past"], vault["profile"]),
                         ([], [], [["allow", "192.168.10.0/24"], ["deny", "all"]]))

    def test_what_the_watcher_did_not_read_is_named(self):
        def missing(payload):
            return Gate.of(Containers(payload, NOW), self.network, self.roads, NAS).payload(Tongue.of("en"))["missing"]
        self.assertEqual(missing(None), "gate.no-snapshot")
        self.assertEqual(missing({"taken": "2026-10-04T19:50:00+00:00"}), "gate.not-read")
        self.assertEqual(missing({"taken": "2026-10-04T19:50:00+00:00", "gate": {"missing": "gate.not-mounted"}}),
                         "gate.not-mounted")

    def test_the_firewall_is_one_sentence_and_an_unread_one_says_so(self):
        def wall(firewall):
            written = {"taken": "x", "gate": {"missing": "", "doors": [], "firewall": firewall}}
            return Gate.of(Containers(written, NOW), self.network, self.roads, NAS).payload(Tongue.of("en"))["wall"]
        self.assertEqual(wall({"missing": "", "on": False, "profile": "default", "rules": 0}), "DSM's firewall is off.")
        self.assertIn("rules: 3", wall({"missing": "", "on": True, "profile": "custom", "rules": 3}))
        self.assertIn("does not know", wall({"missing": "gate.firewall-not-mounted"}))
        self.assertIn("does not know", wall({}))


if __name__ == "__main__":
    unittest.main()

"""What a device or a subnet may reach: the five things a network can be in the fog."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

HARNESS = Path(__file__).resolve().parent / "sight_check.js"
NODE = shutil.which("node")
ANY = {"protocol": "any", "ports": "any port"}


def number(ip: str) -> int:
    a, b, c, d = (int(part) for part in ip.split("."))
    return ((a * 256 + b) * 256 + c) * 256 + d


def span(network: str) -> list:
    base, bits = network.split("/")
    low = number(base)
    return [low, low + 2 ** (32 - int(bits)) - 1]


def opening(source: str, target: str, **kind) -> dict:
    """An opening from an address or network to an address or network, as /api/map gives it."""
    as_range = lambda text: span(text) if "/" in text else [number(text), number(text)]
    return {"source": source, "target": target, "from": [as_range(source)], "to": [as_range(target)],
            **(kind or ANY)}


def road(source: str, target: str, *openings, width: str = "all") -> dict:
    return {"source": source, "target": target, "width": width, "only": "", "openings": list(openings)}


def device(key: str, name: str, segment: str, ip: str) -> dict:
    return {"key": key, "name": name, "homes": [segment], "online": True,
            "seats": [{"ip": ip, "segment": segment, "online": True}]}


#: The home network as it stands: UPS reaches only the NAS on 8065; NAS reaches only some of Lab.
WORLD = {
    "ends": {"internet": "internet", "router": "router"},
    "segments": [{"key": "ups", "network": "192.168.40.0/24"}, {"key": "nas", "network": "192.168.20.0/24"},
                 {"key": "lab", "network": "192.168.30.0/24"}, {"key": "home", "network": "192.168.88.0/24"}],
    "devices": [device("u", "UPS KSTAR", "ups", "192.168.40.200"), device("n", "NAS", "nas", "192.168.20.10"),
                device("h", "Home Assistant", "nas", "192.168.20.40"), device("s", "GPU box", "lab", "192.168.30.20"),
                device("m", "Mac mini", "lab", "192.168.30.10"), device("p", "phone", "home", "192.168.88.56")],
    "roads": [
        road("ups", "nas", opening("192.168.40.0/24", "192.168.20.10", protocol="tcp", ports="8065"), width="ports"),
        road("ups", "internet", opening("192.168.40.0/24", "0.0.0.0/0"), width="most"),
        road("nas", "lab", opening("192.168.20.0/24", "192.168.30.20", protocol="tcp", ports="7990"),
             opening("192.168.20.0/24", "192.168.30.10")),
        road("nas", "ups", opening("192.168.20.0/24", "192.168.40.0/24")),
        road("lab", "nas", opening("192.168.30.0/24", "192.168.20.0/24", protocol="tcp", ports="443"),
             opening("192.168.30.0/24", "192.168.20.0/24", protocol="udp", ports="53")),
        road("home", "nas", opening("192.168.88.56", "192.168.20.0/24")),
        road("home", "lab", opening("192.168.88.0/24", "192.168.30.0/24"), width="shut"),
    ],
}


@unittest.skipUnless(NODE, "node is not installed: the fog's rules cannot be checked")
class SightTest(unittest.TestCase):
    def look(self, **who) -> dict:
        done = subprocess.run([NODE, str(HARNESS), json.dumps(WORLD), json.dumps(who)],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)

    def test_a_subnet_that_reaches_one_machine_sees_that_machine_alone_through_the_dark(self):
        seen = self.look(segment="ups")
        self.assertEqual(seen["ups"], {"state": "home"})
        self.assertEqual(seen["nas"], {"state": "hosts", "hosts": [
            {"device": "n", "name": "NAS", "ip": "192.168.20.10", "ports": ["tcp 8065"]}]})
        self.assertEqual(seen["internet"], {"state": "open"})
        self.assertEqual((seen["lab"], seen["home"]), ({"state": "shut"}, {"state": "shut"}))

    def test_machines_reached_on_every_port_show_through_with_no_ports_written(self):
        hosts = self.look(segment="nas")["lab"]["hosts"]
        self.assertEqual({host["name"]: host["ports"] for host in hosts}, {"GPU box": ["tcp 7990"], "Mac mini": []})

    def test_a_whole_network_on_some_ports_is_striped_with_the_ports(self):
        self.assertEqual(self.look(segment="lab")["nas"], {"state": "ports", "ports": ["tcp 443", "udp 53"]})

    def test_a_rule_for_one_device_is_not_the_subnets_reach_but_is_told_apart(self):
        seen = self.look(segment="home")
        self.assertEqual(seen["nas"], {"state": "some", "members": ["phone"]})
        self.assertEqual(seen["lab"], {"state": "shut"}, "a road the router keeps shut reaches nothing")

    def test_a_device_reaches_what_its_own_address_passes(self):
        self.assertEqual(self.look(device="p")["nas"], {"state": "open"})
        self.assertEqual(self.look(device="u")["nas"]["state"], "hosts")
        self.assertEqual(self.look(device="m")["nas"], {"state": "ports", "ports": ["tcp 443", "udp 53"]})

    def test_a_rule_handed_out_in_pieces_still_reaches_the_whole_network(self):
        """The router splits "the whole of Lab" where one machine has rules of its own: .0–.19,
        .20 and .21–.255 are one network together, not three machines."""
        pieces = [opening("192.168.20.0/24", "192.168.30.0/28"), opening("192.168.20.0/24", "192.168.30.16/28"),
                  opening("192.168.20.0/24", "192.168.30.32/27"), opening("192.168.20.0/24", "192.168.30.64/26"),
                  opening("192.168.20.0/24", "192.168.30.128/25")]
        world = {**WORLD, "roads": [road("nas", "lab", *pieces)]}
        done = subprocess.run([NODE, str(HARNESS), json.dumps(world), json.dumps({"segment": "nas"})],
                              capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(done.stdout)["lab"], {"state": "open"})
        gap = {**WORLD, "roads": [road("nas", "lab", *pieces[:2], *pieces[3:])]}
        done = subprocess.run([NODE, str(HARNESS), json.dumps(gap), json.dumps({"segment": "nas"})],
                              capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(done.stdout)["lab"]["state"], "hosts", "a gap in the pieces is not the whole")

    def test_ports_come_in_the_order_of_their_numbers(self):
        """udp 53 before udp 123: sorted as text, 4752 would come before 53."""
        kinds = [("udp", "123"), ("udp", "4752"), ("udp", "53"), ("udp", "67-68"), ("icmp", "any port"), ("tcp", "53")]
        openings = [opening("192.168.30.0/24", "192.168.20.0/24", protocol=protocol, ports=ports)
                    for protocol, ports in kinds]
        world = {**WORLD, "roads": [road("lab", "nas", *openings, width="ports")]}
        done = subprocess.run([NODE, str(HARNESS), json.dumps(world), json.dumps({"segment": "lab"})],
                              capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(done.stdout)["nas"]["ports"],
                         ["icmp", "tcp 53", "udp 53", "udp 67-68", "udp 123", "udp 4752"])

    def test_with_no_road_at_all_a_network_is_shut(self):
        self.assertEqual(self.look(device="s")["ups"], {"state": "shut"})


if __name__ == "__main__":
    unittest.main()

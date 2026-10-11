"""A made-up home network for the README's pictures and for trying the map without a router:
python3 tools/make_demo.py

Writes demo/snapshot.json, demo/atlas.json, demo/names.json and demo/containers.json — what
the container watcher would have seen on the NAS, DSM's reverse proxy included. Nothing in them
is anybody's:
the networks are the usual 192.168.x ones, the MAC addresses are locally administered
(02:00:00:…), the names are made up, and the outside services are public ones.

The network: Home, Guests, a NAS network, IoT and the Back to Home VPN behind a MikroTik, and
the internet provider's own router beyond the WAN port. Home may go everywhere; the guests reach
the NAS's web apps, and one old tablet of theirs Synology Photos as well; the NAS drives the IoT
devices; everything else between the networks is shut.

To look at it, copy the folder first — the map writes into its data folder as it runs:

    cp -r demo /tmp/lan-map-demo
    LAN_MAP_DATA_DIR=/tmp/lan-map-demo LAN_MAP_SHOW_NETWORKS=127.0.0.0/8 LAN_MAP_ROUTER_HOST=127.0.0.1 python3 -m lan_map
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent / "demo"

#: (network key, title, router address, VLAN or None)
NETWORKS = [
    ("bridge_main", "Home", "192.168.88.1/24", None),
    ("vlan10_guests", "Guests", "192.168.10.1/24", 10),
    ("vlan20_nas", "NAS", "192.168.20.1/24", 20),
    ("vlan30_iot", "IoT", "192.168.30.1/24", 30),
]
VPN = ("back-to-home-vpn", "VPN", "192.168.216.1/24")
WAN = ("ether1", "192.168.1.2/24", "192.168.1.1")

#: (address, name, kind, on Wi-Fi) — a lease each, with the name as its caption.
DEVICES = [
    ("192.168.88.10", "MacBook", "laptop", True),
    ("192.168.88.11", "Desktop", "", False),
    ("192.168.88.12", "Phone", "iphone", True),
    ("192.168.88.13", "Tablet", "tablet", True),
    ("192.168.88.14", "Smart TV", "tv", False),
    ("192.168.88.20", "Access point", "wifi", False),
    ("192.168.10.21", "Guest phone", "phone", True),
    ("192.168.10.22", "Guest laptop", "laptop", True),
    ("192.168.10.23", "Old iPad", "tablet", True),
    ("192.168.20.10", "NAS", "nas", False),
    ("192.168.20.30", "UPS", "ups", False),
    ("192.168.20.40", "Home Assistant", "smart-home", False),
    ("192.168.30.21", "Camera", "camera", True),
    ("192.168.30.22", "Printer", "printer", True),
    ("192.168.30.23", "Thermostat", "thermostat", True),
    ("192.168.30.24", "Robot vacuum", "vacuum", True),
    ("192.168.30.25", "Smart plug", "socket", True),
    ("192.168.30.26", "Speaker", "speaker", True),
]
TRAVEL_PHONE = ("192.168.216.2", "Travel phone")
ISP_ROUTER = ("192.168.1.1", "Provider's router")

#: (comment, packets, fields): the firewall in the router's own order. A rule with no packets
#: has never fired, and grows over with moss on the map.
INPUT = [
    ("defconf: accept established,related,untracked", 812000, {"connection-state": "established,related,untracked"}),
    ("defconf: drop invalid", 140, {"connection-state": "invalid", "action": "drop"}),
    ("defconf: accept ICMP", 9100, {"protocol": "icmp"}),
    ("home: everything to the router", 52000, {"in-interface": "bridge_main"}),
    ("all networks: DNS", 61000, {"in-interface-list": "SEGMENTS", "protocol": "udp", "dst-port": "53"}),
    ("all networks: DNS over TCP", 800, {"in-interface-list": "SEGMENTS", "protocol": "tcp", "dst-port": "53"}),
    ("all networks: DHCP", 3300, {"in-interface-list": "SEGMENTS", "protocol": "udp", "dst-port": "67-68"}),
    ("all networks: time", 1200, {"in-interface-list": "SEGMENTS", "protocol": "udp", "dst-port": "123"}),
    ("defconf: drop all not coming from LAN", 21000, {"in-interface-list": "!LAN", "action": "drop"}),
    ("all networks: nothing else to the router", 650, {"in-interface-list": "SEGMENTS", "action": "drop"}),
]
FORWARD = [
    ("defconf: fasttrack", 2400000, {"connection-state": "established,related", "action": "fasttrack-connection"}),
    ("defconf: accept established,related,untracked", 2600000, {"connection-state": "established,related,untracked"}),
    ("defconf: drop invalid", 310, {"connection-state": "invalid", "action": "drop"}),
    ("everything from WAN: no", 18000, {"in-interface-list": "WAN", "action": "drop"}),
    ("home: everywhere", 98000, {"in-interface": "bridge_main"}),
    ("out: not into the provider's network", 42, {"in-interface-list": "SEGMENTS", "out-interface-list": "WAN",
                                                    "dst-address": "192.168.1.0/24", "action": "drop"}),
    ("all networks: internet", 410000, {"in-interface-list": "SEGMENTS", "out-interface-list": "WAN"}),
    ("guests: the NAS's web apps", 2300, {"in-interface": "vlan10_guests", "out-interface": "vlan20_nas",
                                          "dst-address": "192.168.20.10", "protocol": "tcp", "dst-port": "443"}),
    ("guests: the old iPad to Synology Photos", 870, {"in-interface": "vlan10_guests", "out-interface": "vlan20_nas",
                                                      "src-address": "192.168.10.23", "dst-address": "192.168.20.10",
                                                      "protocol": "tcp", "dst-port": "5001"}),
    ("NAS: Home Assistant drives the devices", 15000, {"in-interface": "vlan20_nas", "out-interface": "vlan30_iot"}),
    ("IoT: to Home Assistant", 0, {"in-interface": "vlan30_iot", "out-interface": "vlan20_nas",
                                   "dst-address": "192.168.20.40", "protocol": "tcp", "dst-port": "8123"}),
    ("VPN: home", 640, {"in-interface": "back-to-home-vpn", "out-interface": "bridge_main"}),
    ("between networks, everything else: no", 5200, {"in-interface-list": "SEGMENTS",
                                                     "out-interface-list": "SEGMENTS", "action": "drop"}),
]

#: (name, address) the router resolved: the outside services the map names.
RESOLVED = [
    ("www.youtube.com", "142.250.74.110"),
    ("api.anthropic.com", "160.79.104.10"),
    ("ipv4-c001-lhr001.1.nflxvideo.net", "45.57.90.1"),
    ("github.com", "140.82.121.4"),
    ("spclient.wg.spotify.com", "35.186.224.25"),
]
#: (from, to, port, how many): the connections the router holds right now.
CONNECTIONS = [
    ("192.168.88.10", "160.79.104.10", 443, 3),
    ("192.168.88.10", "140.82.121.4", 443, 1),
    ("192.168.88.14", "45.57.90.1", 443, 2),
    ("192.168.88.12", "142.250.74.110", 443, 2),
    ("192.168.88.13", "35.186.224.25", 443, 1),
    ("192.168.10.21", "142.250.74.110", 443, 1),
    ("192.168.10.22", "192.168.20.10", 443, 1),
    ("192.168.10.23", "192.168.20.10", 5001, 1),
    ("192.168.20.40", "192.168.30.23", 80, 1),
    ("192.168.20.40", "192.168.30.21", 554, 1),
    ("192.168.20.10", "140.82.121.4", 443, 1),
    ("192.168.216.2", "192.168.88.10", 22, 1),
]


#: (container, project, image, network, published ports, name behind DSM's proxy, its port there)
CONTAINERS = [
    ("homeassistant", "home-assistant", "ghcr.io/home-assistant/home-assistant:2026.10", "host", [], "ha", 8123),
    ("jellyfin", "jellyfin", "jellyfin/jellyfin:10.11", "bridge", ["8096→8096/tcp"], "media", 8096),
    ("vaultwarden", "vaultwarden", "vaultwarden/server:1.37.3", "bridge", ["127.0.0.1:18100→80/tcp"], "vault", 18100),
    ("immich-server", "immich", "ghcr.io/immich-app/immich-server:v2.1", "bridge", ["2283→2283/tcp"], "photos", 2283),
    ("immich-postgres", "immich", "ghcr.io/immich-app/postgres:16", "bridge", [], "", 0),
    ("lan-map", "lan-map", "lan-map:latest", "host", [], "map", 18091),
    ("lan-map-containers", "lan-map", "lan-map:latest", "none", [], "", 0),
]
#: Who DSM's proxy lets in, by name: none is everyone the router lets through.
PROFILES = {"vault": [["allow", "192.168.88.0/24"], ["allow", "192.168.10.0/24"], ["deny", "all"]],
            "map": [["allow", "192.168.88.0/24"], ["deny", "all"]]}


def mac(number: int) -> str:
    """A made-up MAC address: locally administered, 02:00:00:…."""
    return "02:00:00:00:{:02X}:{:02X}".format(number // 256, number % 256)


def network_of(address: str) -> str:
    return address.rsplit(".", 1)[0] + ".0"


def interface_of(address: str) -> str:
    for key, _, router, _ in NETWORKS:
        if router.rsplit(".", 1)[0] == address.rsplit(".", 1)[0]:
            return key
    return VPN[0]


def snapshot(taken: str) -> dict:
    ids = iter(range(1, 10000))
    row = lambda **fields: {".id": f"*{next(ids):X}", "disabled": "false", "dynamic": "false", **fields}
    addresses = [row(address=router, network=network_of(router.split("/")[0]), interface=key,
                     **{"actual-interface": key, "invalid": "false"})
                 for key, _, router, _ in NETWORKS]
    addresses.append(row(address=VPN[2], network=network_of(VPN[2].split("/")[0]), interface=VPN[0],
                         dynamic="true", **{"actual-interface": VPN[0], "invalid": "false"}))
    addresses.append(row(address=WAN[1], network=network_of(WAN[1].split("/")[0]), interface=WAN[0],
                         dynamic="true", **{"actual-interface": WAN[0], "invalid": "false"}))
    interfaces = [row(name=name, type=kind, running="true", **{"mac-address": mac(order + 1)})
                  for order, (name, kind) in enumerate([(WAN[0], "ether"), ("bridge_main", "bridge"),
                                                        ("vlan10_guests", "vlan"), ("vlan20_nas", "vlan"),
                                                        ("vlan30_iot", "vlan"), ("wifi1", "wifi"), ("wifi2", "wifi"),
                                                        (VPN[0], "wg")])]
    lists = [row(name=name, builtin="false", comment="") for name in ("LAN", "WAN", "SEGMENTS")]
    ours = [key for key, *_ in NETWORKS] + [VPN[0]]
    members = ([row(list="LAN", interface=key) for key in ours] + [row(list="WAN", interface=WAN[0])]
               + [row(list="SEGMENTS", interface=key) for key in ours])
    vlans = [row(name=key, interface="bridge_main", **{"vlan-id": str(vlan)}) for key, _, _, vlan in NETWORKS if vlan]
    servers = [row(name=f"dhcp_{key}", interface=key) for key, *_ in NETWORKS]
    leases, arp, wifi = [], [], []
    for order, (address, name, _, wireless) in enumerate(DEVICES):
        key = interface_of(address)
        leases.append(row(address=address, comment=name, server=f"dhcp_{key}", status="bound",
                          **{"active-address": address, "mac-address": mac(256 + order),
                             "host-name": name.replace(" ", "-").replace("'", ""), "last-seen": "1m"}))
        arp.append(row(address=address, interface=key, complete="true", status="reachable", dynamic="true",
                       **{"mac-address": mac(256 + order)}))
        if wireless:
            wifi.append(row(interface="wifi2" if key == "vlan10_guests" else "wifi1",
                            ssid="Guests" if key == "vlan10_guests" else "Home", signal="-55",
                            **{"mac-address": mac(256 + order), "last-activity": "0ms"}))
    arp.append(row(address=ISP_ROUTER[0], interface=WAN[0], complete="true", status="reachable", dynamic="true",
                   **{"mac-address": mac(900)}))
    peers = [row(interface=VPN[0], comment=f"{VPN[0]} {TRAVEL_PHONE[1]}", dynamic="true",
                 **{"allowed-address": f"{TRAVEL_PHONE[0]}/32", "last-handshake": "00:00:40"})]
    filters = []
    for chain, rules in (("input", INPUT), ("forward", FORWARD)):
        for comment, packets, fields in rules:
            fields = {"action": "accept", **fields}
            filters.append(row(chain=chain, comment=comment, packets=str(packets), bytes=str(packets * 900),
                               invalid="false", **fields))
    nat = [row(chain="srcnat", action="masquerade", comment="defconf: masquerade", packets="52000",
               bytes="31000000", invalid="false", **{"out-interface-list": "WAN"})]
    routes = [row(gateway=WAN[2], dynamic="true", **{"dst-address": "0.0.0.0/0"})]
    dns_static = [row(name="router.lan.example", address="192.168.88.1", type="A"),
                  row(name="nas.lan.example", address="192.168.20.10", type="A"),
                  row(name="ha.lan.example", address="192.168.20.40", type="A")]
    dns_cache = [row(name=name, data=address, type="A", ttl="5m") for name, address in RESOLVED]
    connections, port = [], 50000
    for source, target, to, many in CONNECTIONS:
        for _ in range(many):
            port += 1
            connections.append(row(protocol="tcp", **{"src-address": f"{source}:{port}",
                                                      "dst-address": f"{target}:{to}",
                                                      "tcp-state": "established"}))
    resource = {"uptime": "2w3d04:05:06", "version": "7.20 (stable)", "board-name": "hAP ax3",
                "architecture-name": "arm64", "cpu-load": "4", "free-memory": "812000000",
                "total-memory": "1073741824", "platform": "MikroTik"}
    tables = {
        "system/resource": resource, "ip/address": addresses, "interface": interfaces,
        "interface/vlan": vlans, "interface/bridge/port": [], "interface/bridge/vlan": [],
        "interface/list": lists, "interface/list/member": members, "ip/dhcp-server": servers,
        "ip/dhcp-server/network": [], "ip/dhcp-server/lease": leases, "ip/arp": arp, "ip/neighbor": [],
        "ip/dns/static": dns_static, "ip/dns/cache": dns_cache, "ip/route": routes,
        "interface/wifi/registration-table": wifi, "interface/wireguard/peers": peers,
        "ip/firewall/filter": filters, "ip/firewall/nat": nat, "ip/firewall/address-list": [],
        "ip/firewall/raw": [], "ip/firewall/mangle": [], "ip/ipsec/policy": [],
        "ip/firewall/connection": connections,
    }
    return {"taken": taken, "tables": tables, "missing": {}}


def atlas() -> dict:
    devices = {mac(256 + order): ({"name": name, "kind": kind} if kind else {"name": name})
               for order, (_, name, kind, _) in enumerate(DEVICES)}
    devices[mac(900)] = {"name": ISP_ROUTER[1], "kind": "router"}
    segments = {key: {"title": title, **({"trusted": True} if key == "bridge_main" else {})}
                for key, title, _, _ in NETWORKS}
    segments[VPN[0]] = {"title": VPN[1]}
    return {"segments": segments, "devices": devices, "same": []}


def containers(taken: str) -> dict:
    """What the container watcher writes: the NAS's containers and DSM's own gate."""
    found = []
    for name, project, image, network, ports, served, _ in CONTAINERS:
        found.append({"name": name, "project": project, "service": name, "folder": f"/volume1/docker/{project}",
                      "image": image, "state": "running", "health": "healthy" if network != "none" else "",
                      "started": "2026-10-01T08:00:00Z", "finished": "", "exit_code": 0, "restarts": 0,
                      "network": network, "ports": ports,
                      "host_ports": sorted({int(port.split("→")[0].rsplit(":", 1)[-1]) for port in ports}),
                      "served": f"{served}.lan.example" if served else ""})
    doors = [{"name": f"{served}.lan.example", "ports": [443], "to": f"http://127.0.0.1:{port}",
              "profile": PROFILES.get(served)}
             for _, _, _, _, _, served, port in CONTAINERS if served]
    folders = sorted({project for _, project, *_ in CONTAINERS})
    return {"taken": taken, "every": 0, "host": {"name": "nas", "os": "Synology NAS (containerized)", "docker": "24.0.2"},
            "apps": "/volume1/docker", "folders": [{"folder": one, "compose": "compose.yaml"} for one in folders],
            "containers": sorted(found, key=lambda one: (one["project"], one["service"], one["name"])),
            "gate": {"missing": "", "doors": sorted(doors, key=lambda door: door["name"]),
                     "firewall": {"missing": "", "on": False, "profile": "default", "rules": 0}}}


def main() -> int:
    DEMO.mkdir(exist_ok=True)
    taken = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for name, payload in (("snapshot.json", snapshot(taken)), ("atlas.json", atlas()),
                          ("names.json", {"names": {}}), ("containers.json", containers(taken))):
        (DEMO / name).write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"the demo network is in {DEMO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

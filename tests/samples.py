"""Snapshots for tests: exactly the rows a test speaks of, everything else empty."""
from lan_map.snapshot import Snapshot

TAKEN = "2026-09-20T05:32:28+00:00"


def snapshot(**tables) -> Snapshot:
    full = {path: [] for path in Snapshot.PATHS}
    full.update(tables)
    return Snapshot(TAKEN, full, {})


def address(ip, interface, network, dynamic="false"):
    return {"address": ip, "interface": interface, "actual-interface": interface,
            "network": network, "dynamic": dynamic, "disabled": "false"}


def lease(ip, server, mac, name="", status="bound", comment=None, last=None):
    row = {"address": ip, "server": server, "mac-address": mac, "host-name": name, "status": status}
    if comment:
        row["comment"] = comment
    if last is not None:
        row["last-seen"] = last
    return row


def rule(action, chain="forward", packets="1", **fields):
    row = {"chain": chain, "action": action, "packets": packets, "bytes": "100", "comment": ""}
    row.update({key.replace("_", "-"): value for key, value in fields.items()})
    return row


HOME = address("192.168.88.1/24", "bridge_main", "192.168.88.0")
LAB = address("192.168.20.1/24", "vlan20_lab", "192.168.20.0")
SERVERS = [{"name": "home", "interface": "bridge_main"}, {"name": "lab", "interface": "vlan20_lab"}]
MEMBERS = [{"list": "LAN", "interface": "bridge_main"}, {"list": "WAN", "interface": "ether5"}]

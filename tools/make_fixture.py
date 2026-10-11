"""Turns a real snapshot into an anonymous sample for the tests: python3 tools/make_fixture.py

What is replaced: MAC addresses, device names and captions, Wi-Fi network names, neighbour names.
What stays: network addresses, the firewall rules with their comments, the counters, DNS names.
What never gets this far: secrets. The snapshot is read through `Snapshot`, which drops them, so
a snapshot written before they were dropped cannot carry a VPN key into git.
The model and rule-reader tests rest on those, and there is nothing personal in them.

The replacement runs right through: one and the same name always becomes one and the same
invented one. So a NAS standing in two networks stays one device in two networks in the sample.
Numbering follows the order things are met, not a hash: the original cannot be recovered.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lan_map.snapshot import Snapshot  # noqa: E402  (the tool runs as a script, not a package)

#: The fields that get replaced: field name → what to call the replacement.
FIELDS = {
    "mac-address": "mac", "active-mac-address": "mac", "src-mac-address": "mac",
    "host-name": "name", "active-host-name": "name", "identity": "name",
    "client-id": "id", "active-client-id": "id",
    "ssid": "wifi",
}
#: Captions the owner writes by hand: they name a device, not a rule.
COMMENTED = ("ip/dhcp-server/lease", "ip/arp", "ip/firewall/address-list")
#: People's names: rule comments stay as they are, but names leave them. A machine cannot tell a
#: person's name from a service's, so the list is written by hand — in data/people.txt, one name
#: a line, beside the snapshot and out of git: in git the names would be the very thing this
#: tool takes out.
PEOPLE_FILE = "people.txt"
#: A MAC hides inside text too: an interface's .about field holds the access point's MAC.
MAC = re.compile(r"\b(?:[0-9A-F]{2}:){5}[0-9A-F]{2}\b", re.I)


class Pseudonyms:
    """Hands out an invented name for every real one and remembers what it handed out."""

    def __init__(self):
        self.given: dict = {}

    def of(self, kind: str, value: str) -> str:
        if not value:
            return value
        key = (kind, value)
        if key not in self.given:
            number = 1 + sum(1 for k in self.given if k[0] == kind)
            self.given[key] = (f"02:00:00:{number // 65536 % 256:02x}:{number // 256 % 256:02x}:{number % 256:02x}"
                               if kind == "mac" else f"{kind}-{number:02d}")
        return self.given[key]


def clean(payload: dict, people: tuple = ()) -> dict:
    names = Pseudonyms()
    for path, rows in payload["tables"].items():
        for row in rows if isinstance(rows, list) else [rows]:
            for field, kind in FIELDS.items():
                if isinstance(row.get(field), str):
                    row[field] = names.of(kind, row[field])
            if path in COMMENTED and row.get("comment"):
                row["comment"] = names.of("caption", row["comment"])
            for field, value in row.items():
                if isinstance(value, str):
                    row[field] = scrub(value, names, people)
    return payload


def scrub(value: str, names: Pseudonyms, people: tuple = ()) -> str:
    """Takes MAC addresses and people's names out of any text."""
    value = MAC.sub(lambda found: names.of("mac", found.group(0).upper()), value)
    for person in people:
        value = re.sub(person, names.of("name", person), value, flags=re.I)
    return value


def main() -> int:
    base = Path(__file__).resolve().parent.parent
    source, target = base / "data" / "snapshot.json", base / "fixtures" / "snapshot.json"
    if not source.is_file():
        print(f"no snapshot at {source}: run `python3 -m lan_map` first", file=sys.stderr)
        return 1
    listed = base / "data" / PEOPLE_FILE
    if not listed.is_file():
        print(f"no {listed}: write the names of the people at home into it, one a line "
              "(an empty file says there are none)", file=sys.stderr)
        return 1
    people = tuple(line.strip() for line in listed.read_text(encoding="utf-8").splitlines()
                   if line.strip() and not line.startswith("#"))
    payload = clean(Snapshot.read(source).to_payload(), people)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"the sample is ready: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

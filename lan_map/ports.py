"""Which doors stand open on a device.

A knock is an ordinary connection closed at once: the map sends nothing and reads nothing.
A door that opens means somebody is listening behind it. Who exactly, the map does not know
and does not find out: it learns the number of the door and says who usually lives behind one.
So the caption is a guess by number, and it is called a guess.

There are some seventy doors in the list, not all 65535. A full sweep means minutes of waiting
and looks like an attack from outside, while the doors people actually use are few.

We knock over TCP only. A closed UDP door stays silent exactly as an open one does, and no
honest answer comes from there — the map will not lie about it.
"""
from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from ipaddress import ip_address

from .tongue import Said


@dataclass(frozen=True)
class Door:
    """A door: its number and who usually lives behind it."""
    port: int
    #: What the service is called. A proper name (ssh, https) stands as it is; a common noun
    #: is a key, and the dictionary says it in the reader's language.
    name: str

    @property
    def about(self) -> str:
        """The key of the caption. One door, one line in the dictionary."""
        return f"door.{self.port}"


#: In order of number. Names only: what lives behind each door is said in web/lang/*.json.
DOORS: tuple = tuple(Door(port, name) for port, name in (
    (21, "ftp"),
    (22, "ssh"),
    (23, "telnet"),
    (25, "smtp"),
    (53, "dns"),
    (80, "http"),
    (110, "pop3"),
    (111, "rpcbind"),
    (135, "msrpc"),
    (139, "netbios"),
    (143, "imap"),
    (443, "https"),
    (445, "smb"),
    (515, "lpd"),
    (548, "afp"),
    (554, "rtsp"),
    (587, "smtp"),
    (631, "ipp"),
    (873, "rsync"),
    (902, "vmware"),
    (1400, "sonos"),
    (1883, "mqtt"),
    (2049, "nfs"),
    (2222, "ssh"),
    (2375, "docker"),
    (2376, "docker"),
    (3000, "door.web"),
    (3128, "proxy"),
    (3306, "mysql"),
    (3389, "rdp"),
    (3493, "nut"),
    (4444, "door.web"),
    (5000, "DSM"),
    (5001, "DSM"),
    (5006, "door.web"),
    (5432, "postgres"),
    (5555, "adb"),
    (5678, "n8n"),
    (5900, "vnc"),
    (6379, "redis"),
    (7000, "airplay"),
    (8000, "door.web"),
    (8006, "proxmox"),
    (8008, "door.web"),
    (8009, "cast"),
    (8065, "mattermost"),
    (8080, "door.web"),
    (8081, "door.web"),
    (8096, "jellyfin"),
    (8123, "home assistant"),
    (8200, "dlna"),
    (8443, "door.web"),
    (8888, "door.web"),
    (9000, "door.web"),
    (9090, "door.web"),
    (9100, "door.print"),
    (9200, "elastic"),
    (11434, "ollama"),
    (19999, "netdata"),
    (25565, "minecraft"),
    (25566, "minecraft"),
    (25567, "minecraft"),
    (32400, "plex"),
    (49152, "door.web"),
    (50000, "DSM"),
    (50001, "DSM"),
    (50002, "DSM"),
))


#: Doors we never knock at, but can still name. The map knocks at our own houses only, while a
#: walk goes out into the world far more often than it goes next door — and "17.242.218.132:5223"
#: says nothing at all. Many of these are udp, where a knock proves nothing either way.
AFIELD: tuple = tuple(Door(port, name) for port, name in (
    (67, "dhcp"),
    (68, "dhcp"),
    (69, "tftp"),
    (88, "kerberos"),
    (123, "ntp"),
    (137, "netbios"),
    (138, "netbios"),
    (161, "snmp"),
    (162, "snmp"),
    (179, "bgp"),
    (389, "ldap"),
    (465, "smtp"),
    (500, "ipsec"),
    (514, "syslog"),
    (636, "ldap"),
    (853, "dns"),
    (993, "imap"),
    (995, "pop3"),
    (1194, "openvpn"),
    (1701, "l2tp"),
    (1723, "pptp"),
    (1812, "radius"),
    (1813, "radius"),
    (1900, "ssdp"),
    (3478, "stun"),
    (3479, "stun"),
    (4500, "ipsec"),
    (5060, "sip"),
    (5061, "sip"),
    (5222, "xmpp"),
    (5223, "door.apple-push"),
    (5228, "door.google-push"),
    (5229, "door.google-push"),
    (5230, "door.google-push"),
    (5353, "mdns"),
    (5355, "llmnr"),
    (5938, "teamviewer"),
    (8291, "winbox"),
    (8728, "door.router-api"),
    (8729, "door.router-api"),
    (8883, "mqtt"),
    (27017, "mongodb"),
    (51820, "wireguard"),
))

#: Every door we can name at all, knocked at or not.
NAMES: dict = {door.port: door.name for door in DOORS + AFIELD}

#: The few doors that mean something else over udp. The number is the same, the neighbour
#: behind it is not: 5678 is n8n when a program waits there for a browser, and MikroTik's own
#: neighbour discovery when it is shouted at the whole network at once.
BY_UDP: dict = {5678: "door.mndp"}


def behind(port, protocol: str = "") -> str:
    """Who usually lives behind this door — a guess by number, and it is called a guess.

    Empty when the number says nothing: better a bare port than a confident wrong name."""
    try:
        number = int(port)
    except (TypeError, ValueError):
        return ""
    if protocol == "udp" and number in BY_UDP:
        return BY_UDP[number]
    return NAMES.get(number, "")


class Locked(ValueError):
    """An address we will not knock at. The reason is a phrase, said in the reader's language."""

    def __init__(self, said: Said):
        super().__init__(said.key)
        self.said = said


class Knocker:
    """Knocks on one device's doors and tells which of them opened."""

    #: How long we wait for an answer. Longer is truer on slow devices, and slower for everyone.
    WAIT = 0.7
    #: How many doors we try at once.
    HANDS = 48

    def __init__(self, doors=DOORS, wait: float = WAIT, hands: int = HANDS):
        self.doors = tuple(doors)
        self.wait = wait
        self.hands = hands

    @staticmethod
    def house(ip: str) -> str:
        """An address we may knock at: our own house only, the map never goes outside."""
        try:
            address = ip_address(ip)
        except ValueError as error:
            raise Locked(Said.of("knock.not-an-address")) from error
        if not address.is_private or address.is_loopback or address.is_unspecified:
            raise Locked(Said.of("knock.only-at-home"))
        return str(address)

    def knock(self, ip: str, port: int) -> bool:
        try:
            with socket.create_connection((ip, port), self.wait):
                return True
        except OSError:
            return False

    @staticmethod
    def watchpost(ip: str) -> str:
        """Where the map knocks from.

        This is worth saying out loud: the knock comes from the map, at the map's own address,
        not from whoever is looking at it. If a closed border lies between the two, every door
        stays silent, and without this line an empty answer would read as "all shut".

        There is no connection here: the address only picks an outgoing one for a UDP socket."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect((ip, 9))
                return probe.getsockname()[0]
        except OSError:
            return ""

    def open_doors(self, ip: str) -> dict:
        """A round of every door. Returns what goes to the page unchanged."""
        ip = self.house(ip)
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=self.hands) as hands:
            answers = list(hands.map(lambda door: (door, self.knock(ip, door.port)), self.doors))
        opened = [{"port": door.port, "name": door.name, "about": door.about}
                  for door, yes in answers if yes]
        return {"ip": ip, "from": self.watchpost(ip), "knocked": len(self.doors), "open": opened,
                "took": round(time.monotonic() - started, 1)}

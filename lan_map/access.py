"""Who is shown the map, and who may drag things on it.

A device is known by its address, so everything rests on one thing: how to learn the real
address behind a request. Behind DSM's reverse proxy, nginx appends it as the last item of
X-Forwarded-For. Everything to the left of that was sent by the client and can be forged.

Lab reaches the NAS through the router's masquerade, that is from 192.168.88.1. So it may
look at the map but not move things: that address is on the list of exceptions.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .tongue import Said, Tongue


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    #: The device's address as far as it could be learnt; None means it could not, and then "no".
    address: str | None
    #: Why not, as a phrase waiting for a language. Empty when the answer is yes.
    reason: object = ""

    def payload(self, tongue: Tongue | None = None) -> dict:
        return {"allowed": self.allowed, "address": self.address,
                "reason": (tongue or Tongue.of()).tell(self.reason)}


class Doorman:
    def __init__(self, show, move, deny, trusted_proxies):
        #: The "who may see" list changes by tick box, so it is asked for every time.
        self.show = show if callable(show) else (lambda fixed=tuple(show): fixed)
        self.move = tuple(move)
        self.deny = tuple(deny)
        self.trusted_proxies = tuple(trusted_proxies)

    def may_see(self, peer: str, forwarded_for: str | None) -> Verdict:
        return self._decide(peer, forwarded_for, self.show(), (), Said.of("door.look"))

    def may_move(self, peer: str, forwarded_for: str | None) -> Verdict:
        return self._decide(peer, forwarded_for, self.move, self.deny, Said.of("door.move"))

    def _decide(self, peer, forwarded_for, allowed, denied, what) -> Verdict:
        address = self.address(peer, forwarded_for)
        if address is None:
            return Verdict(False, None, Said.of("door.no-address"))
        if self._inside(address, denied):
            return Verdict(False, str(address), Said.of("door.not-from-here", address=address,
                                                        what=what))
        if not self._inside(address, allowed):
            where = ", ".join(str(net) for net in allowed) or Said.of("door.empty-list")
            return Verdict(False, str(address),
                           Said.of("door.wrong-network", address=address, what=what, where=where))
        return Verdict(True, str(address), "")

    def address(self, peer: str, forwarded_for: str | None):
        peer_ip = self._address(peer)
        if peer_ip is None:
            return None
        if not forwarded_for or not self._inside(peer_ip, self.trusted_proxies):
            return peer_ip
        return self._address(forwarded_for.split(",")[-1])

    @staticmethod
    def _address(text: str):
        try:
            ip = ipaddress.ip_address(text.strip())
        except ValueError:
            return None
        return ip.ipv4_mapped if ip.version == 6 and ip.ipv4_mapped is not None else ip

    @staticmethod
    def _inside(ip, networks) -> bool:
        return any(ip.version == net.version and ip in net for net in networks)

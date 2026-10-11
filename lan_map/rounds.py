"""Rounds on a schedule: a snapshot by itself, with nobody pressing a button.

Both kinds are off by default, and the map asks the router only on POST /api/refresh: the
button, the page opened on an old snapshot, an agent before it reads. Every walk to the router
is a login it writes into its log, three lines each; on a schedule they were two lines in five
of the router's whole log, read by nobody. LAN_MAP_REFRESH_MINUTES and LAN_MAP_NAMES_MINUTES
switch them back on.

Each kind of round is one quiet thread: if the router does not answer, that goes in the log
and we wait for the next round. Bringing the server down over it is not allowed: the map must
go on showing at least the previous snapshot.

There are two kinds. The snapshot; and a look into the router's DNS cache alone, because the
names in it live for minutes and a snapshot sees only those that happened to be alive at its
moment. On 5 October 2026 the looks every five minutes caught 982 of the 4648 names learned in
5.8 hours, a fifth, beside twelve snapshots.
"""
from __future__ import annotations

import logging
import threading
from typing import ClassVar

log = logging.getLogger("lan_map")


class Rounds:
    """The snapshot round. A kind of round is what it does and what the log calls it."""

    WHAT: ClassVar[str] = "snapshot"

    def __init__(self, app, minutes: int):
        self.app = app
        self.minutes = minutes
        self.stopping = threading.Event()

    def job(self) -> dict:
        return self.app.refresh()

    @staticmethod
    def done(result: dict) -> str:
        return result.get("taken", "")

    def start(self):
        """The rounds thread, or None when there is no schedule. Zero minutes means "do not"."""
        if self.minutes <= 0:
            return None
        thread = threading.Thread(target=self.run, name=f"lan-map-{self.WHAT}", daemon=True)
        thread.start()
        log.info("%s on a schedule: once every %d min", self.WHAT, self.minutes)
        return thread

    def run(self) -> None:
        while not self.stopping.wait(self.minutes * 60):
            self.once()

    def once(self) -> bool:
        """One round. Returns False when it failed — which is no reason to fall over."""
        try:
            result = self.job()
        except Exception as error:
            log.warning("the scheduled %s failed: %s", self.WHAT, error)
            return False
        log.info("scheduled %s: %s", self.WHAT, self.done(result))
        return True

    def stop(self) -> None:
        self.stopping.set()


class NameRounds(Rounds):
    """A look into the router's DNS cache every few minutes, and the names written down."""

    WHAT: ClassVar[str] = "names"

    def job(self) -> dict:
        return self.app.remember_names()

    @staticmethod
    def done(result: dict) -> str:
        return f"{result['names']} remembered, {result['new']} new"

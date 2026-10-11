"""A fresh look at everything the map tells, answered only once it is written.

The map reads two snapshots, and neither is taken on a schedule: the router's, by the map itself;
and the host's containers with DSM's gate, by the container watcher — a service of its own, with
no network and so no way to be called. Both are taken when somebody asks, and this is the asking:
the Refresh button, the page opened on a snapshot older than ten minutes, an agent before it
reads. Nothing else walks to the router, so its log is not filled with the map's logins.

POST /api/refresh takes both anew and answers only when both are written. The router's snapshot
the map takes itself, walking to the router. The watcher it asks with a note in the data folder
they share, data/containers.ask, and it waits for a snapshot taken after the note was left. Two
guards keep many readers from becoming a crowd at the router's door: one walk at a time, so
whoever asks while a walk is under way waits for that very walk; and a snapshot younger than half
a minute counts as fresh and is not taken again.

DSM's reverse proxy gives up on an answer after sixty seconds, so the watcher is waited for no
longer than thirty: a watcher that stays silent is said to be silent, not waited for forever.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, ClassVar

from .containers import Watcher, docker_time
from .tongue import Said, Tongue


@dataclass
class Refresh:
    """One call of POST /api/refresh: both snapshots fresh, or the reason one is not."""

    #: The map: its walk to the router, its data folder, its clock, the watcher's last snapshot.
    app: object
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic

    #: A snapshot this young is fresh enough: taken again, it would only cost the router a walk.
    FRESH: ClassVar[timedelta] = timedelta(seconds=30)
    #: How long the watcher is waited for. Its round takes seconds; half a minute of silence means
    #: it is not running, or is older than the map and reads no notes.
    WAIT: ClassVar[float] = 30.0
    #: How often the map looks whether the watcher has written.
    STEP: ClassVar[float] = 0.5

    def run(self, tongue: Tongue) -> dict:
        asked = self.app.clock()
        since = asked - self.FRESH
        # The note goes first, the walk second: the watcher's round and the router's walk overlap.
        noted = self.note(since, asked)
        snapshot = self.snapshot(since, tongue)
        containers = self.containers(asked, noted, tongue)
        fresh = snapshot["fresh"] and containers["fresh"]
        done = {"fresh": fresh, "snapshot": snapshot, "containers": containers}
        if not fresh:
            done["error"] = "; ".join(part["why"] for part in (snapshot, containers) if part["why"])
        return done

    def note(self, since: datetime, asked: datetime):
        """A note asking the watcher for a round, unless its latest snapshot is fresh already.
        True: left; False: not needed; a phrase: why it could not be left."""
        taken = self.taken(self.app.containers())
        if taken is not None and taken >= since:
            return False
        try:
            (self.app.data_dir / Watcher.ASK).write_text(asked.isoformat(timespec="seconds"), encoding="utf-8")
        except OSError as error:
            return Said.of("refresh.no-note", why=error.strerror or error)
        return True

    def snapshot(self, since: datetime, tongue: Tongue) -> dict:
        """The router's snapshot, as the map's own walk left it: one walk at a time, none needed
        when the latest is fresh. A walk that failed is told by its reason."""
        done = self.app.refreshed(since)
        why = done.get("why")
        return {"taken": done.get("taken") or "", "fresh": why is None, "walked": done.get("walked", False),
                "why": tongue.tell(why) if why is not None else ""}

    def containers(self, asked: datetime, noted, tongue: Tongue) -> dict:
        """The watcher's snapshot: fresh already, or the one written after the note — waited for."""
        known = self.app.containers()
        if noted is False:
            return {"taken": known.payload["taken"], "fresh": True, "asked": False, "why": ""}
        if noted is not True:
            return self.stale(known, False, tongue.tell(noted))
        # The watcher writes whole seconds: a snapshot within the very second the note was left counts.
        wanted = asked.replace(microsecond=0)
        deadline = self.monotonic() + self.WAIT
        while True:
            taken = self.taken(known)
            if taken is not None and taken >= wanted:
                return {"taken": known.payload["taken"], "fresh": True, "asked": True, "why": ""}
            if self.monotonic() >= deadline:
                return self.stale(known, True, tongue.tell(Said.of("refresh.watcher-silent", seconds=int(self.WAIT))))
            self.sleep(self.STEP)
            known = self.app.containers()

    @staticmethod
    def stale(known, asked: bool, why: str) -> dict:
        return {"taken": (known.payload or {}).get("taken", ""), "fresh": False, "asked": asked, "why": why}

    @staticmethod
    def taken(known):
        """When the watcher's snapshot was taken; None when there is none, or no readable time."""
        return docker_time((known.payload or {}).get("taken"))

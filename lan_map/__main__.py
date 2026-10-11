"""`python -m lan_map` starts the map. `python -m lan_map snapshot` takes a fresh snapshot.

This is the way in: the one place that reads the real environment and the real clock and
hands them to the objects.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
from pathlib import Path

from .access import Doorman
from .audience import Audience
from .rounds import NameRounds, Rounds
from .routeros import RouterError, RouterRest
from .server import MapApp
from .settings import Settings, SettingsError
from .snapshot import Snapshot, utc_now
from .tongue import Tongue

BASE = Path(__file__).resolve().parent.parent


def settings(need_password: bool) -> Settings:
    return Settings.from_env(os.environ, base=BASE, need_password=need_password)


def router(chosen: Settings) -> RouterRest:
    """The way to the router.

    The password is read afresh every time rather than remembered at start-up: drop the file
    next to the snapshot and Refresh works, with no need to restart the container."""
    password = chosen.router_password or Settings.password(os.environ)
    return RouterRest(chosen.router_host, chosen.router_user, password, chosen.router_cert)


def taker(chosen: Settings):
    """What takes a snapshot."""
    def take():
        return Snapshot.take(router(chosen), clock=utc_now)

    return take


def asker(chosen: Settings):
    """What reads one table from the router: for the rounds lighter than a snapshot."""
    def ask(path: str):
        return router(chosen).get(path)

    return ask


def take_snapshot() -> int:
    chosen = settings(need_password=True)
    rest = RouterRest(chosen.router_host, chosen.router_user, chosen.router_password,
                      chosen.router_cert)
    try:
        snapshot = Snapshot.take(rest, clock=utc_now)
    except RouterError as err:
        print(f"lan-map: {Tongue.of().tell(err.said)}", file=sys.stderr)
        return 1
    where = snapshot.write(chosen.data_dir / "snapshot.json")
    print(f"snapshot {snapshot.taken} -> {where}")
    for path, count in snapshot.counts().items():
        print(f"  {path:<34} {count}")
    for path, why in snapshot.missing.items():
        print(f"  {path:<34} missing: {Tongue.of().tell(why)}")
    return 0


def serve() -> int:
    chosen = settings(need_password=False)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Snapshots taken before secrets were dropped still hold them, and so does any copy put
    # back from a backup. Every start leaves the disk without them.
    scrubbed = Snapshot.scrub(chosen.data_dir / "snapshot.json")
    if scrubbed:
        logging.getLogger("lan_map").info("secrets removed from %d stored snapshots", len(scrubbed))
    audience = Audience(chosen.show, chosen.data_dir / "settings.json")
    doorman = Doorman(audience.networks, chosen.move, chosen.deny, chosen.trusted_proxies)
    app = MapApp(BASE / "web", chosen.data_dir, doorman, take=taker(chosen), ask=asker(chosen),
                 audience=audience, here=lambda: MapApp.address_toward(chosen.router_host),
                 proc_net=Path("/proc/net"))
    logging.getLogger("lan_map").info("names remembered: %d, the stored snapshots included",
                                      app.remember_stored())
    rounds = [Rounds(app, chosen.refresh_minutes), NameRounds(app, chosen.names_minutes)]
    for one in rounds:
        one.start()
    server = app.make_server(chosen.host, chosen.port)
    logging.getLogger("lan_map").info("the map listens on %s:%s, data in %s",
                                      chosen.host, chosen.port, chosen.data_dir)
    # The map is PID 1 of its container, and PID 1 has no default for SIGTERM: without this,
    # `docker compose up -d` waits ten seconds before it kills the map, and DSM's proxy answers
    # 502 all that while. SIGTERM ends it as Ctrl-C does. Leaving at once loses nothing: the
    # snapshot and the settings are written whole or not at all.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for one in rounds:
            one.stop()
        server.server_close()
    return 0


def main(argv) -> int:
    what = argv[1] if len(argv) > 1 else "serve"
    if what not in ("serve", "snapshot"):
        print(f"lan-map: no such command \u00ab{what}\u00bb; there are serve and snapshot",
              file=sys.stderr)
        return 2
    try:
        return take_snapshot() if what == "snapshot" else serve()
    except SettingsError as err:
        print(f"lan-map: {Tongue.of().tell(err.said)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

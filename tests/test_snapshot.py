import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from lan_map.routeros import RouterError
from lan_map.tongue import Said
from lan_map.snapshot import Snapshot

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "snapshot.json"


class FakeRest:
    """Hands back a table from a dictionary; what is not there the router "did not give"."""

    def __init__(self, tables):
        self.tables = tables
        self.asked = []

    def get(self, path):
        self.asked.append(path)
        if path not in self.tables:
            raise RouterError(Said.of("router.no-answer", path=path, why="a test"))
        return self.tables[path]


def clock():
    return datetime(2026, 9, 20, 5, 32, 28, tzinfo=timezone.utc)


def full_tables(**overrides):
    tables = {path: [] for path in Snapshot.PATHS}
    tables.update(overrides)
    return tables


class SnapshotTest(unittest.TestCase):
    def test_takes_every_table_it_needs(self):
        rest = FakeRest(full_tables())
        snapshot = Snapshot.take(rest, clock)
        self.assertEqual(rest.asked, list(Snapshot.PATHS))
        self.assertEqual(snapshot.taken, "2026-09-20T05:32:28+00:00")
        self.assertEqual(snapshot.missing, {})

    def test_a_table_the_router_does_not_have_is_missing_not_empty(self):
        tables = full_tables()
        del tables["interface/wifi/registration-table"]
        snapshot = Snapshot.take(FakeRest(tables), clock)
        self.assertIn("interface/wifi/registration-table", snapshot.missing)
        with self.assertRaises(KeyError):
            snapshot.rows("interface/wifi/registration-table")

    def test_a_table_it_cannot_do_without_stops_the_snapshot(self):
        tables = full_tables()
        del tables["ip/firewall/filter"]
        with self.assertRaises(RouterError):
            Snapshot.take(FakeRest(tables), clock)

    def test_written_and_read_back_is_the_same(self):
        snapshot = Snapshot.take(FakeRest(full_tables(**{"ip/address": [{"address": "192.168.88.1/24"}]})), clock)
        with tempfile.TemporaryDirectory() as tmp:
            again = Snapshot.read(snapshot.write(Path(tmp) / "snapshot.json"))
        self.assertEqual(again.to_payload(), snapshot.to_payload())

    def test_counts_one_object_as_one_row(self):
        snapshot = Snapshot.take(FakeRest(full_tables(**{"system/resource": {"version": "7.24.2"}})), clock)
        self.assertEqual(snapshot.counts()["system/resource"], 1)

    def test_the_real_snapshot_has_what_the_map_needs(self):
        """The sample came from a real router: the model and rule-reader tests rest on it."""
        snapshot = Snapshot.read(FIXTURE)
        self.assertEqual(snapshot.missing, {})
        self.assertEqual(len(snapshot.rows("ip/firewall/filter")), 71)
        addresses = {row["address"] for row in snapshot.rows("ip/address")}
        self.assertLessEqual({"192.168.88.1/24", "192.168.20.1/24", "192.168.30.1/24", "192.168.40.1/24"}, addresses)
        rule = snapshot.rows("ip/firewall/filter")[0]
        self.assertLessEqual({"chain", "action", "bytes", "packets", "disabled"}, set(rule))


if __name__ == "__main__":
    unittest.main()


#: A Back To Home peer as the router gives it: every field it really has, and the two it must not keep.
PEER = {".id": "*5", "name": "peer5", "interface": "back-to-home-vpn", "disabled": "false",
        "dynamic": "true", "comment": "back-to-home-vpn iPhone", "responder": "true",
        "allowed-address": "192.168.216.3/32", "client-address": "192.168.216.3/32",
        "client-allowed-address": "", "client-dns": "192.168.216.1",
        "client-endpoint": "example.vpn.mynetname.net", "client-keepalive": "30s",
        "current-endpoint-address": "203.0.113.7", "current-endpoint-port": "4752",
        "endpoint-address": "", "endpoint-port": "0", "persistent-keepalive": "30s",
        "last-handshake": "1m30s", "rx": "394692", "tx": "716752", "public-key": "PUBLIC=",
        "private-key": "PRIVATE-DO-NOT-KEEP=", "preshared-key": "SHARED-DO-NOT-KEEP="}


class SecretsTest(unittest.TestCase):
    """The one thing a snapshot does not keep as the router gave it."""

    def taken(self) -> Snapshot:
        return Snapshot.take(FakeRest(full_tables(**{"interface/wireguard/peers": [PEER]})), clock)

    def test_a_peer_keeps_everything_but_its_keys(self):
        kept = self.taken().rows("interface/wireguard/peers")[0]
        self.assertEqual(set(PEER) - set(kept), {"private-key", "preshared-key"})
        self.assertEqual(kept["public-key"], "PUBLIC=")

    def test_no_secret_reaches_the_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            where = self.taken().write(Path(tmp) / "snapshot.json")
            written = [path.read_text(encoding="utf-8") for path in Snapshot.stored(where)]
        self.assertEqual(len(written), 2, "the snapshot and its copy on the shelf")
        for text in written:
            self.assertNotIn("DO-NOT-KEEP", text)

    def test_every_spelling_the_router_uses_is_a_secret(self):
        for field in ("private-key", "preshared-key", "vpn-private-key", "vpn-peer-private-key",
                      "wpa2-pre-shared-key", "security.passphrase", "password", "ipsec-secret",
                      "authentication-password", "auth-key", "tcp-md5-key", "psk"):
            with self.subTest(field):
                self.assertTrue(Snapshot.secret(field))

    def test_nothing_the_map_reads_is_taken_for_a_secret(self):
        """Every field a real router gave, and every field of a peer but its keys, survives."""
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fields = {field for rows in raw["tables"].values()
                  for row in (rows if isinstance(rows, list) else [rows]) for field in row}
        fields |= set(PEER) - {"private-key", "preshared-key"}
        self.assertEqual({field for field in fields if Snapshot.secret(field)}, set())

    def test_snapshots_written_before_are_scrubbed_where_they_lie(self):
        """The current one, the one stepped aside and the shelf: all three held keys."""
        dirty = {"taken": "2026-09-23T15:00:00+00:00", "missing": {},
                 "tables": {"interface/wireguard/peers": [PEER],
                            "ip/address": [{"address": "192.168.88.1/24"}]}}
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "snapshot.json"
            Snapshot.shelf(current).mkdir()
            for path in (current, Snapshot.before(current),
                         Snapshot.shelf(current) / "2026-09-23T15-00-00+00-00.json"):
                path.write_text(json.dumps(dirty), encoding="utf-8")
            first, again = Snapshot.scrub(current), Snapshot.scrub(current)
            texts = [path.read_text(encoding="utf-8") for path in Snapshot.stored(current)]
            kept = json.loads(current.read_text(encoding="utf-8"))
        self.assertEqual(len(first), 3)
        self.assertEqual(again, [], "a clean snapshot is left alone")
        for text in texts:
            self.assertNotIn("DO-NOT-KEEP", text)
        self.assertEqual(kept["taken"], dirty["taken"])
        self.assertEqual(kept["tables"]["ip/address"], [{"address": "192.168.88.1/24"}])
        self.assertEqual(kept["tables"]["interface/wireguard/peers"][0]["last-handshake"], "1m30s")

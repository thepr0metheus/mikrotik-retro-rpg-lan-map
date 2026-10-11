"""What listens on the host, as the kernel's TCP tables tell it, and the next port for a new app."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lan_map.listening import FreePort, Listening

HEAD = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
LOOPBACK, ANY = "0100007F", "00000000"
LOOPBACK6 = "00000000000000000000000001000000"


def row(number: int, local: str, port: int, state: str, remote: str = "00000000:0000") -> str:
    """One socket as /proc/net/tcp writes it: the port in hex, the state in hex, 0A listening."""
    return (f"{number:4d}: {local}:{port:04X} {remote} {state} 00000000:00000000 00:00000000 00000000"
            f"  1026        0 {40000 + number} 1 0000000000000000 100 0 0 10 0\n")


class ListeningTest(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.net = Path(folder.name)

    def write(self, name: str, *rows: str) -> None:
        (self.net / name).write_text(HEAD + "".join(rows), encoding="ascii")

    def test_listening_ports_come_from_both_tables_and_connections_do_not(self):
        self.write("tcp", row(0, LOOPBACK, 18091, "0A"), row(1, ANY, 443, "0A"),
                   row(2, LOOPBACK, 18150, "01", remote=f"{LOOPBACK}:C350"))
        self.write("tcp6", row(0, LOOPBACK6, 18140, "0A"), row(1, LOOPBACK6, 18160, "06"))
        self.assertEqual(Listening.read(self.net), Listening(frozenset({18091, 443, 18140})))

    def test_with_ipv6_off_the_ipv4_table_is_enough(self):
        self.write("tcp", row(0, LOOPBACK, 18091, "0A"))
        self.assertEqual(Listening.read(self.net), Listening(frozenset({18091})))

    def test_with_no_tables_the_ports_are_not_known_rather_than_none(self):
        self.assertEqual(Listening.read(self.net), Listening(None, "free-port.no-tables"))
        self.assertEqual(Listening.read(None), Listening(None, "free-port.no-tables"))

    def test_a_row_that_does_not_read_makes_the_whole_table_unknown(self):
        self.write("tcp", row(0, LOOPBACK, 18091, "0A"), "   1: nonsense 00000000:0000 0A\n")
        self.assertEqual(Listening.read(self.net), Listening(None, "free-port.unreadable"))


class FreePortTest(unittest.TestCase):
    def test_the_first_port_nothing_holds_in_steps_of_ten(self):
        self.assertEqual(FreePort.first(set()), 18150)
        self.assertEqual(FreePort.first({18150, 18160, 18175}), 18170)

    def test_with_every_port_taken_there_is_none(self):
        self.assertIsNone(FreePort.first(set(range(18150, 18991, 10))))


if __name__ == "__main__":
    unittest.main()

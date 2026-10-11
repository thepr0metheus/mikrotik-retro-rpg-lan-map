import socket
import unittest
from contextlib import closing

from lan_map.ports import AFIELD, DOORS, Door, Knocker, Locked, behind
from lan_map.tongue import Tongue


class DoorsTest(unittest.TestCase):
    def test_the_list_is_sorted_and_says_something_about_every_door(self):
        ports = [door.port for door in DOORS]
        self.assertEqual(ports, sorted(ports), "the doors are out of order")
        self.assertEqual(len(ports), len(set(ports)), "a door is described twice")
        plain = Tongue.of("en")
        for door in DOORS:
            with self.subTest(door.port):
                self.assertTrue(door.name)
                self.assertNotEqual(plain.say(door.about), door.about,
                                    "the dictionary has no line for this door")

    def test_the_doors_we_only_name_are_in_order_and_hold_no_twins(self):
        """Two lists, one set of numbers: a door named twice would answer twice, differently."""
        afield = [door.port for door in AFIELD]
        self.assertEqual(afield, sorted(afield), "the doors afield are out of order")
        both = [door.port for door in DOORS + AFIELD]
        self.assertEqual(len(both), len(set(both)), "a door is in both lists")
        for door in AFIELD:
            with self.subTest(door.port):
                self.assertTrue(door.name)


class HouseTest(unittest.TestCase):
    def test_the_map_knocks_only_into_its_own_network(self):
        self.assertEqual(Knocker.house("192.168.88.5"), "192.168.88.5")
        for stranger in ("8.8.8.8", "127.0.0.1", "0.0.0.0", "not an address", ""):
            with self.subTest(stranger), self.assertRaises(Locked):
                Knocker.house(stranger)


class KnockTest(unittest.TestCase):
    """A real knock: the door is opened by an ordinary socket in this very process."""

    def setUp(self):
        self.door = socket.socket()
        self.door.bind(("127.0.0.1", 0))
        self.door.listen(1)
        self.addCleanup(self.door.close)
        self.port = self.door.getsockname()[1]

    def test_an_open_door_answers(self):
        self.assertTrue(Knocker(wait=2).knock("127.0.0.1", self.port))

    def test_a_closed_door_stays_silent(self):
        with closing(socket.socket()) as shut:
            shut.bind(("127.0.0.1", 0))
            closed = shut.getsockname()[1]
        self.assertFalse(Knocker(wait=2).knock("127.0.0.1", closed))

    def test_the_answer_tells_which_doors_opened_and_from_where_we_knocked(self):
        class Near(Knocker):
            """The same knock at a neighbouring address: this tests the round, not the ban."""
            house = staticmethod(lambda ip: ip)

        doors = [Door(self.port, "test"), Door(self.port + 1, "test")]
        answer = Near(doors=doors, wait=2).open_doors("127.0.0.1")
        self.assertEqual([row["port"] for row in answer["open"]], [self.port])
        self.assertEqual(answer["open"][0]["about"], f"door.{self.port}")
        self.assertEqual(answer["knocked"], 2)
        self.assertTrue(answer["from"], "the map must say which address it knocked from")


if __name__ == "__main__":
    unittest.main()


class BehindTest(unittest.TestCase):
    """What lives behind a number — and when the number alone is not enough to say."""

    def test_a_knocked_door_is_named(self):
        self.assertEqual(behind("22"), "ssh")

    def test_a_door_we_never_knock_at_is_named_all_the_same(self):
        """A walk goes out to 123 and 5223 far more often than to anything we knock at."""
        self.assertEqual(behind("123"), "ntp")
        self.assertEqual(behind("5223"), "door.apple-push")

    def test_over_udp_a_door_may_hold_somebody_else(self):
        """5678 is n8n when a program waits there, and MikroTik's neighbours when it is shouted."""
        self.assertEqual(behind("5678", "tcp"), "n8n")
        self.assertEqual(behind("5678", "udp"), "door.mndp")

    def test_a_number_that_says_nothing_says_nothing(self):
        """Better a bare port than a confident wrong name."""
        self.assertEqual(behind("64321"), "")
        self.assertEqual(behind(""), "")

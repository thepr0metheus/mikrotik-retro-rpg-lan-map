import unittest

from lan_map.spans import ANY_PORT, NOBODY, NO_PORTS, PORT_HIGH, Space, Unclear


class ReadingTest(unittest.TestCase):
    def test_the_forms_a_rule_uses(self):
        self.assertEqual(Space.addresses("192.168.88.200").size, 1)
        self.assertEqual(Space.addresses("192.168.20.0/24").size, 256)
        self.assertEqual(Space.addresses("192.168.40.107-192.168.40.108").size, 2)
        self.assertEqual(Space.addresses("192.168.88.10,192.168.88.20").size, 2)

    def test_no_port_means_any_port(self):
        self.assertEqual(Space.ports("").size, PORT_HIGH + 1)
        self.assertEqual(Space.ports("8100-8199").size, 100)
        self.assertEqual(Space.ports("25565,25566").ports_text(), "25565-25566")

    def test_a_condition_can_be_turned_inside_out(self):
        """`!192.168.88.0/24` the router reads as "everything but" — and so do we."""
        rest = Space.addresses("!192.168.88.0/24")
        self.assertNotIn(int.from_bytes(bytes([192, 168, 88, 7])), rest)
        self.assertIn(int.from_bytes(bytes([192, 168, 20, 7])), rest)
        self.assertEqual(Space.ports("!445").size, PORT_HIGH)

    def test_what_we_do_not_understand_we_say_so(self):
        for text in ("почта", "192.168.88.300", "192.168.88.0/33"):
            with self.subTest(text):
                self.assertRaises(Unclear, Space.addresses, text)
        for text in ("много", "70000", "445,"):
            with self.subTest(text):
                self.assertRaises(Unclear, Space.ports, text)


class CountingTest(unittest.TestCase):
    def setUp(self):
        self.guests = Space.addresses("192.168.40.0/24")
        self.kids = Space.addresses("192.168.40.107-192.168.40.108")

    def test_what_is_left_after_taking_a_piece_out(self):
        rest = self.guests - self.kids
        self.assertEqual(rest.size, 254)
        self.assertEqual((rest & self.kids).size, 0)
        self.assertEqual((rest | self.kids), self.guests)

    def test_pieces_cover_the_whole_and_never_straddle_a_bound(self):
        pieces = self.guests.split(self.kids.bounds())
        whole = Space()
        for piece in pieces:
            whole = whole | piece
            self.assertIn((piece & self.kids).size, (0, piece.size), "a piece is cut by a rule's bound")
        self.assertEqual(whole, self.guests)

    def test_a_space_without_rules_stays_one_piece(self):
        self.assertEqual(self.guests.split(set()), [self.guests])


class SayingTest(unittest.TestCase):
    def test_a_range_that_is_a_network_is_called_a_network(self):
        self.assertEqual(Space.addresses("192.168.20.0/24").address_text(), "192.168.20.0/24")
        self.assertEqual(Space.addresses("192.168.88.200").address_text(), "192.168.88.200")
        self.assertEqual(Space.addresses("192.168.40.107-192.168.40.108").address_text(),
                         "192.168.40.107-192.168.40.108")

    def test_nothing_is_called_nothing(self):
        """These are codes, not words: which language says them is decided much later."""
        self.assertEqual(Space().address_text(), NOBODY)
        self.assertEqual(Space().ports_text(), NO_PORTS)
        self.assertEqual(Space.ports("").ports_text(), ANY_PORT)


if __name__ == "__main__":
    unittest.main()

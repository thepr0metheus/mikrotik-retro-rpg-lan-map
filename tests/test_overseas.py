"""Who is at the far end of a walk out of the island."""
import unittest
from ipaddress import ip_network

from lan_map.overseas import HOUSES, Overseas


SEA = Overseas()


class ByNameTest(unittest.TestCase):
    def test_a_house_owns_everything_under_its_domain(self):
        self.assertEqual(SEA.by_name("rr2.sn-h5bupjvh-ucnr.googlevideo.com"), "YouTube")
        self.assertEqual(SEA.by_name("imap.gmail.com"), "Gmail")

    def test_the_root_dot_the_router_writes_is_no_obstacle(self):
        """He stores a resolved name as "17.courier2-push-apple.com.akadns.net." — with the dot."""
        self.assertEqual(SEA.by_name("17.courier2-push-apple.com.akadns.net."), "Akamai")

    def test_the_longest_ending_wins(self):
        """googlevideo.com is not under google.com, but the order must not decide this anyway."""
        self.assertEqual(SEA.by_name("something.youtube.com"), "YouTube")
        self.assertEqual(SEA.by_name("www.googleapis.com"), "Google")

    def test_a_name_nobody_claims_is_left_alone(self):
        for stranger in ("router.lan", "example.org", "", "...", "com"):
            with self.subTest(stranger):
                self.assertEqual(SEA.by_name(stranger), "")

    def test_a_house_next_door_is_not_this_house(self):
        """notgoogle.com ends with the same letters and belongs to somebody else entirely."""
        self.assertEqual(SEA.by_name("notgoogle.com"), "")


class ByBlockTest(unittest.TestCase):
    def test_an_address_is_read_by_the_water_it_floats_in(self):
        self.assertEqual(SEA.by_block("17.57.146.22"), "Apple")
        self.assertEqual(SEA.by_block("142.251.151.6"), "Google")
        self.assertEqual(SEA.by_block("149.154.167.41"), "Telegram")

    def test_water_nobody_owns_stays_water(self):
        for stranger in ("213.157.200.141", "192.168.88.10", "not an address", ""):
            with self.subTest(stranger):
                self.assertEqual(SEA.by_block(stranger), "")

    def test_the_narrowest_block_answers_first(self):
        """8.8.8.8/32 sits inside nobody here, but the order is what keeps it that way."""
        widths = [block.prefixlen for block, _ in SEA.waters]
        self.assertEqual(widths, sorted(widths, reverse=True))


class WhoseTest(unittest.TestCase):
    def test_a_name_beats_the_water(self):
        """That cache stands in the provider's own network, and it is still YouTube."""
        self.assertEqual(SEA.whose("rr2.sn-h5bupjvh-ucnr.googlevideo.com", "213.157.200.141"),
                         {"house": "YouTube", "guessed": False, "by": "name"})

    def test_without_a_name_the_water_is_all_there_is_and_it_is_a_guess(self):
        self.assertEqual(SEA.whose("", "142.251.151.6"),
                         {"house": "Google", "guessed": True, "by": "block"})

    def test_nobody_is_nobody(self):
        self.assertEqual(SEA.whose("", "213.157.200.141"), {"house": "", "guessed": True, "by": ""})

    def test_a_remembered_name_names_the_house_but_only_as_a_guess(self):
        """The router gave that name to this address before; the address may have moved on."""
        self.assertEqual(SEA.whose("rr2.sn-h5bupjvh-ucnr.googlevideo.com", "142.251.151.6", remembered=True),
                         {"house": "YouTube", "guessed": True, "by": "memory"})

    def test_a_remembered_name_nobody_claims_leaves_the_house_to_the_water(self):
        """The page then shows the name itself: `by` tells it the house came from the block."""
        self.assertEqual(SEA.whose("http-intake.logs.us5.datadoghq.com", "142.251.151.6", remembered=True),
                         {"house": "Google", "guessed": True, "by": "block"})


class TheTableItselfTest(unittest.TestCase):
    def test_no_ending_belongs_to_two_houses(self):
        """One name, one answer: two would make the answer depend on the order of the list."""
        endings = [ending for house in HOUSES for ending in house.names]
        self.assertEqual(len(endings), len(set(endings)))

    def test_no_block_is_written_twice(self):
        blocks = [ip_network(block) for house in HOUSES for block in house.blocks]
        self.assertEqual(len(blocks), len(set(blocks)))

    def test_every_house_is_known_by_something(self):
        for house in HOUSES:
            with self.subTest(house.name):
                self.assertTrue(house.name)
                self.assertTrue(house.names or house.blocks)

    def test_no_house_claims_the_water_at_home(self):
        """A block covering a private range would name our own castles after a stranger."""
        home = [ip_network("192.168.0.0/16"), ip_network("10.0.0.0/8"),
                ip_network("172.16.0.0/12")]
        for block, name in SEA.waters:
            with self.subTest(f"{name} {block}"):
                self.assertFalse(any(block.overlaps(one) for one in home))


class DomainTest(unittest.TestCase):
    """A name without a house is grouped by the domain somebody registered."""

    def test_the_last_two_labels_make_the_domain(self):
        self.assertEqual(Overseas.domain("http-intake.logs.us5.datadoghq.com."), "datadoghq.com")

    def test_a_country_s_shared_second_level_takes_a_third_label(self):
        self.assertEqual(Overseas.domain("www.bbc.co.uk"), "bbc.co.uk")

    def test_a_short_name_is_its_own_domain(self):
        self.assertEqual(Overseas.domain("featureassets.org"), "featureassets.org")


class TheFiveAskedForTest(unittest.TestCase):
    def test_they_are_all_there(self):
        for name, under in (("Pinterest", "www.pinterest.com"), ("AliExpress", "ae01.alicdn.com"),
                            ("Ozon", "cdn1.ozone.ru"), ("Wildberries", "basket-12.wbbasket.ru"),
                            ("X (Twitter)", "api.twitter.com")):
            with self.subTest(name):
                self.assertEqual(SEA.by_name(under), name)


if __name__ == "__main__":
    unittest.main()

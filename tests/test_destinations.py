import unittest

from lan_map.destinations import Destinations
from lan_map.roads import INTERNET


def walk(to, name="", remembered=False, house="", by="", count=1, where=INTERNET):
    return {"to": to, "name": name, "remembered": remembered, "house": house, "by": by,
            "guessed": by != "name", "where": where, "count": count}


def known(*walks) -> list:
    return Destinations.of({"192.168.88.10": list(walks)}).payload()["known"]


class KnownTest(unittest.TestCase):
    def test_a_house_named_by_a_name_is_the_answer(self):
        self.assertEqual(known(walk("142.250.1.1", "rr2.sn-x.googlevideo.com", house="YouTube", by="name")),
                         [{"who": "YouTube", "by": "name", "count": 1, "addresses": 1}])

    def test_a_name_without_a_house_is_grouped_by_its_domain(self):
        """A hundred hostnames of one service make one line."""
        self.assertEqual(known(walk("34.149.66.165", "http-intake.logs.us5.datadoghq.com", remembered=True),
                               walk("34.149.66.166", "browser-intake.us5.datadoghq.com", count=2)),
                         [{"who": "datadoghq.com", "by": "name", "count": 3, "addresses": 2}])

    def test_a_remembered_name_outranks_the_block(self):
        """The name was given to this very address, the block only to the street."""
        self.assertEqual(known(walk("34.149.66.165", "http-intake.logs.us5.datadoghq.com",
                                    remembered=True, house="Google", by="block")),
                         [{"who": "datadoghq.com", "by": "memory", "count": 1, "addresses": 1}])

    def test_the_block_is_the_last_answer_and_says_so(self):
        self.assertEqual(known(walk("142.251.151.6", house="Google", by="block")),
                         [{"who": "Google", "by": "block", "count": 1, "addresses": 1}])

    def test_a_line_says_the_surest_way_any_of_its_walks_was_known(self):
        self.assertEqual(known(walk("142.251.151.6", house="Google", by="block"),
                               walk("142.250.1.1", "www.google.com", house="Google", by="name"))[0]["by"],
                         "name")

    def test_the_busiest_come_first(self):
        self.assertEqual([one["who"] for one in known(walk("1.1.1.1", house="Cloudflare", by="block"),
                                                      walk("17.57.1.1", house="Apple", by="block", count=5))],
                         ["Apple", "Cloudflare"])


class UnknownTest(unittest.TestCase):
    def test_what_nothing_can_name_is_listed_not_passed_over(self):
        payload = Destinations.of({"192.168.88.10": [walk("46.49.10.17", count=2),
                                                     walk("84.200.39.139")]}).payload()
        self.assertEqual(payload["unknown"], [{"ip": "46.49.10.17", "count": 2},
                                              {"ip": "84.200.39.139", "count": 1}])
        self.assertEqual(payload["known"], [])

    def test_a_walk_at_home_is_neither(self):
        """An address at home is named by whoever lives at it, not by this page."""
        payload = Destinations.of({"192.168.88.10": [walk("192.168.20.10", where="vlan20_nas")]}).payload()
        self.assertEqual(payload, {"known": [], "unknown": []})

    def test_the_list_stops_where_it_would_turn_into_a_log(self):
        walks = [walk(f"203.0.113.{last}") for last in range(1, 60)]
        self.assertEqual(len(Destinations.of({"192.168.88.10": walks}).unknown), Destinations.UNKNOWN_MOST)


if __name__ == "__main__":
    unittest.main()

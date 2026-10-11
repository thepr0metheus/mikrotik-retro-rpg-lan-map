import tempfile
import unittest
from pathlib import Path

from lan_map.settings import Settings, SettingsError
from lan_map.tongue import Tongue

EN = Tongue.of("en")

BASE = Path("/opt/lan-map")


class SettingsTest(unittest.TestCase):
    def test_defaults_point_at_the_home_router(self):
        settings = Settings.from_env({"LAN_MAP_ROUTER_PASSWORD": "x"}, base=BASE)
        self.assertEqual((settings.router_host, settings.router_user), ("192.168.88.1", "lan-map"))
        self.assertEqual(settings.router_cert, BASE / "config" / "router-cert.pem")
        self.assertEqual(settings.data_dir, BASE / "data")

    def test_password_from_a_file(self):
        cases = ["LAN_MAP_ROUTER_PASSWORD=секрет\n", "# комментарий\n\nсекрет\n",
                 "# подсказка\nLAN_MAP_ROUTER_PASSWORD=секрет\n"]
        for text in cases:
            with self.subTest(text=text.splitlines()[0]):
                with tempfile.TemporaryDirectory() as tmp:
                    where = Path(tmp) / "router.env"
                    where.write_text(text, encoding="utf-8")
                    settings = Settings.from_env({"LAN_MAP_ROUTER_PASSWORD_FILE": str(where)}, base=BASE)
                    self.assertEqual(settings.router_password, "секрет")

    def test_without_a_password_it_says_what_to_set(self):
        with self.assertRaises(SettingsError) as caught:
            Settings.from_env({}, base=BASE)
        self.assertIn("LAN_MAP_ROUTER_PASSWORD_FILE", EN.tell(caught.exception.said))

    def test_an_empty_file_is_not_a_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            where = Path(tmp) / "router.env"
            where.write_text("# только подсказка\n\n", encoding="utf-8")
            with self.assertRaises(SettingsError) as caught:
                Settings.from_env({"LAN_MAP_ROUTER_PASSWORD_FILE": str(where)}, base=BASE)
            self.assertEqual(caught.exception.said.key, "settings.password-file-empty")

    def test_a_missing_file_says_so(self):
        with self.assertRaises(SettingsError) as caught:
            Settings.from_env({"LAN_MAP_ROUTER_PASSWORD_FILE": "/нет/такого"}, base=BASE)
        self.assertEqual(caught.exception.said.key, "settings.password-unreadable")


if __name__ == "__main__":
    unittest.main()

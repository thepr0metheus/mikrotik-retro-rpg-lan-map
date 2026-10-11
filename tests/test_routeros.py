import io
import json
import unittest
import urllib.error

from lan_map.routeros import RouterError, RouterRest
from lan_map.tongue import Tongue

EN = Tongue.of("en")


class FakeOpener:
    """Answers from a table: the value is a response body, or an error to raise."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def open(self, request, timeout=None):
        self.asked.append((request.full_url, dict(request.header_items())))
        answer = self.answers[request.full_url]
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(answer)


def http_error(code, detail=None):
    body = io.BytesIO(json.dumps({"detail": detail, "error": code}).encode()) if detail else io.BytesIO(b"")
    return urllib.error.HTTPError("https://router/rest/x", code, "reason", {}, body)


def rest(answers):
    client = RouterRest.__new__(RouterRest)
    client.opener = FakeOpener(answers)
    client.base = "https://192.168.88.1/rest"
    client.auth = "Basic x"
    client.timeout = 1
    return client


class RouterRestTest(unittest.TestCase):
    def test_table_comes_back_as_rows(self):
        client = rest({"https://192.168.88.1/rest/ip/address": b'[{"address":"192.168.88.1/24"}]'})
        self.assertEqual(client.get("ip/address"), [{"address": "192.168.88.1/24"}])

    def test_login_refused_says_about_the_password(self):
        client = rest({"https://192.168.88.1/rest/ip/address": http_error(401)})
        with self.assertRaises(RouterError) as caught:
            client.get("ip/address")
        self.assertEqual(caught.exception.said.key, "router.bad-password")

    def test_missing_policy_says_which_rights_are_needed(self):
        client = rest({"https://192.168.88.1/rest/ip/address": http_error(500, "std failure: not allowed (9)")})
        with self.assertRaises(RouterError) as caught:
            client.get("ip/address")
        self.assertIn("read, rest-api and api", EN.tell(caught.exception.said))

    def test_silence_and_nonsense_are_errors_too(self):
        cases = {"https://192.168.88.1/rest/a": urllib.error.URLError("connection refused"),
                 "https://192.168.88.1/rest/b": b"<html>not json</html>"}
        for path, expected in (("a", "router.no-answer"), ("b", "router.not-json")):
            with self.subTest(path=path):
                with self.assertRaises(RouterError) as caught:
                    rest(cases).get(path)
                self.assertEqual(caught.exception.said.key, expected)

    def test_only_get_and_always_with_the_password(self):
        client = rest({"https://192.168.88.1/rest/ip/address": b"[]"})
        client.get("/ip/address/")
        url, headers = client.opener.asked[0]
        self.assertEqual(url, "https://192.168.88.1/rest/ip/address")
        self.assertEqual(headers["Authorization"], "Basic x")
        self.assertFalse(hasattr(RouterRest, "post"), "the client has no way to write")


if __name__ == "__main__":
    unittest.main()

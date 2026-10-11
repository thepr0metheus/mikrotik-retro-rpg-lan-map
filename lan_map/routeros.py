"""Reading the router: REST over https, GET only, trusting exactly its own certificate.

The map changes nothing on the router, so the client simply has no way to write: it sends GET
and nothing else. The user on the router has no write permission either — two locks, not one.
"""
from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from .tongue import Said


class RouterError(RuntimeError):
    """No data from the router: no answer, a refused login, or something that is not JSON."""

    def __init__(self, said: Said):
        super().__init__(said.key)
        self.said = said


class RouterRest:
    """The router's REST client. A table path ("ip/firewall/filter") becomes one GET."""

    AGENT = "lan-map (read-only)"

    def __init__(self, host: str, user: str, password: str, cert_file: Path, timeout: float = 8.0):
        context = ssl.create_default_context(cafile=str(cert_file))
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
        self.base = f"https://{host}/rest"
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        self.timeout = timeout

    def get(self, path: str):
        """A router table as a list of dict rows; values are strings, as RouterOS gives them."""
        request = urllib.request.Request(
            f"{self.base}/{path.strip('/')}",
            headers={"Authorization": self.auth, "Accept": "application/json", "User-Agent": self.AGENT})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as err:
            raise RouterError(self.refusal(path, err)) from err
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise RouterError(Said.of("router.no-answer", path=path,
                                      why=getattr(err, "reason", err))) from err
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise RouterError(Said.of("router.not-json", path=path)) from err

    @staticmethod
    def refusal(path: str, err: urllib.error.HTTPError) -> Said:
        """The router's refusal in words: 401 and "not allowed" call for different fixes."""
        detail = ""
        try:
            detail = json.loads(err.read().decode("utf-8")).get("detail", "")
        except (ValueError, OSError):
            detail = ""  # the body is optional; the status code already says enough
        if err.code == 401:
            return Said.of("router.bad-password", path=path)
        if "not allowed" in detail:
            return Said.of("router.not-allowed", path=path, code=err.code, detail=detail)
        return Said.of("router.refused", path=path, code=err.code, detail=detail or err.reason)

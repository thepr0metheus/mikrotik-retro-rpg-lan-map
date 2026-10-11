"""What this copy of the map is made of, named as osv.dev names it: GET /api/packages.

A check of known vulnerabilities must see what is installed, not what the project asks for. The
map asks for nothing beyond Python's own library, so what it is made of is its image: Python, the
few distributions that come with it, and Alpine's packages, on which Python itself runs. The
page's scripts are the map's own code: no library comes with them. Each entry is a query osv.dev
answers as it is, {ecosystem, name, version}, so whoever checks needs to know nothing of the map.

Alpine's packages are named by their origin, the source package: libcrypto3 and libssl3 both come
from openssl, and osv.dev knows only that name. Asked by the installed names it finds nothing, and
nothing would read as "no vulnerabilities".
"""
from __future__ import annotations

import importlib.metadata
import platform
import re
from pathlib import Path


class InstalledPackages:
    """The packages of this copy of the map, read once: a running container does not change."""

    #: Alpine's database of installed packages, under the root.
    APK_DB = "lib/apk/db/installed"

    def __init__(self, root: Path = Path("/"), distributions=importlib.metadata.distributions,
                 python_version=platform.python_version):
        self.root = Path(root)
        self.distributions = distributions
        self.python_version = python_version
        self.known = None

    def listing(self) -> dict:
        """{runtime, os, packages}. `os` is None when the system cannot be told, and `os.listed`
        is False when its packages cannot be read: a check must then say it did not see them,
        rather than read an empty list as a clean one."""
        if self.known is None:
            system = self.system()
            packages = self.python()
            if system and system["listed"]:
                packages += self.alpine(system["version"])
            self.known = {"runtime": {"name": "python", "version": self.python_version()},
                          "os": system, "packages": packages}
        return self.known

    def system(self) -> dict | None:
        """The system's ID and VERSION_ID from os-release, and whether its packages can be read."""
        try:
            text = (self.root / "etc" / "os-release").read_text(encoding="utf-8")
        except OSError:
            return None
        fields = {}
        for line in text.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                fields[key.strip()] = value.strip().strip("\"'")
        name, version = fields.get("ID"), fields.get("VERSION_ID", "")
        if not name:
            return None
        listed = (name == "alpine" and bool(re.match(r"\d+\.\d+", version))
                  and (self.root / self.APK_DB).is_file())
        return {"name": name, "version": version, "listed": listed}

    def python(self) -> list:
        """Python's distributions, by their names as PyPI compares them."""
        found = {}
        for distribution in self.distributions():
            if not distribution.name:
                continue
            name = re.sub(r"[-_.]+", "-", distribution.name).lower()
            found[(name, distribution.version)] = {"ecosystem": "PyPI", "name": name,
                                                   "version": distribution.version}
        return sorted(found.values(), key=lambda package: (package["name"], package["version"]))

    def alpine(self, os_version: str) -> list:
        """Alpine's packages by their origin (`o:`), the version (`V:`) as apk wrote it, and the
        ecosystem as osv.dev names the release: Alpine:v3.22."""
        ecosystem = "Alpine:v" + ".".join(os_version.split(".")[:2])
        found = {}
        text = (self.root / self.APK_DB).read_text(encoding="utf-8", errors="replace")
        for record in text.split("\n\n"):
            fields = {}
            for line in record.splitlines():
                if len(line) > 2 and line[1] == ":":
                    fields.setdefault(line[0], line[2:])
            name, version = fields.get("o") or fields.get("P"), fields.get("V")
            if name and version:
                found[(name, version)] = {"ecosystem": ecosystem, "name": name, "version": version}
        return sorted(found.values(), key=lambda package: (package["name"], package["version"]))

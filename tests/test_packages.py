import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from lan_map.packages import InstalledPackages

# Three records of Alpine's database of installed packages, as apk writes it: libcrypto3 and
# libssl3 come from one source package, openssl; musl names its own.
APK = """C:Q1abc=
P:libcrypto3
V:3.5.4-r0
A:x86_64
o:openssl
F:usr/lib
R:libcrypto.so.3
a:0:0:755

C:Q1def=
P:libssl3
V:3.5.4-r0
o:openssl

P:musl
V:1.2.5-r10
o:musl
"""


def distributions():
    return [SimpleNamespace(name=name, version=version) for name, version in
            [("pip", "25.2"), ("Some_Thing", "1.0"), ("some-thing", "1.0"), (None, "1")]]


class InstalledPackagesTest(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def copy(self, os_release=None, apk=APK) -> InstalledPackages:
        if os_release is not None:
            (self.root / "etc").mkdir(exist_ok=True)
            (self.root / "etc" / "os-release").write_text(os_release)
        if apk is not None:
            database = self.root / InstalledPackages.APK_DB
            database.parent.mkdir(parents=True, exist_ok=True)
            database.write_text(apk)
        return InstalledPackages(self.root, distributions=distributions, python_version=lambda: "3.14.0")

    def test_alpine_packages_go_by_their_source_beside_python_and_its_own(self):
        """osv.dev knows openssl, not libcrypto3: asked by the installed name it finds nothing."""
        listing = self.copy('NAME="Alpine Linux"\nID=alpine\nVERSION_ID=3.22.2\n').listing()
        self.assertEqual(listing["runtime"], {"name": "python", "version": "3.14.0"})
        self.assertEqual(listing["os"], {"name": "alpine", "version": "3.22.2", "listed": True})
        self.assertEqual([(one["ecosystem"], one["name"], one["version"]) for one in listing["packages"]], [
            ("PyPI", "pip", "25.2"), ("PyPI", "some-thing", "1.0"),
            ("Alpine:v3.22", "musl", "1.2.5-r10"), ("Alpine:v3.22", "openssl", "3.5.4-r0"),
        ])

    def test_a_system_it_cannot_list_says_so_rather_than_look_clean(self):
        debian = self.copy('ID=debian\nVERSION_ID="12"\n', apk=None).listing()
        self.assertEqual(debian["os"], {"name": "debian", "version": "12", "listed": False})
        self.assertEqual({one["ecosystem"] for one in debian["packages"]}, {"PyPI"})

    def test_no_system_to_tell_is_none(self):
        listing = self.copy(apk=None).listing()
        self.assertIsNone(listing["os"])
        self.assertEqual({one["ecosystem"] for one in listing["packages"]}, {"PyPI"})

    def test_alpine_without_its_database_is_not_listed(self):
        self.assertFalse(self.copy("ID=alpine\nVERSION_ID=3.22.2\n", apk=None).listing()["os"]["listed"])


if __name__ == "__main__":
    unittest.main()

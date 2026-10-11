"""The words the map says out loud, in whatever language the reader asked for.

The map itself thinks in codes: a road is `shut`, a finding is `mossy`. Codes never reach
the eye. Every one of them is spelled out here, from a dictionary that lives next to the page
in `web/lang/` so that the browser and the server read the very same file — two copies would
drift apart, and then the picture and the text would disagree.

English is the language the map is written in, and the one every other falls back to. A new
language is a new file in that directory: nothing here needs to learn its name.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

#: Where the dictionaries live. The page is served from the same directory.
HOME = Path(__file__).resolve().parent.parent / "web" / "lang"
#: The language the map is written in: a key missing elsewhere is looked up here.
PLAIN = "en"
#: A hole in a phrase: `{name}` is filled in by whoever says it.
HOLE = re.compile(r"\{(\w+)\}")

_kept: dict = {}


def forget() -> None:
    """Drop what was read from disk. Tests change the dictionaries under our feet."""
    _kept.clear()


def _read(code: str) -> dict:
    if code not in _kept:
        path = HOME / f"{code}.json"
        try:
            words = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            words = {}
        _kept[code] = words if isinstance(words, dict) else {}
    return _kept[code]


def known() -> tuple:
    """Every language on the shelf: its code and what it calls itself.

    English first — it is the default — then the rest as they come alphabetically."""
    found = []
    for path in sorted(HOME.glob("*.json")) if HOME.is_dir() else []:
        words = _read(path.stem)
        if words:
            found.append({"code": path.stem, "name": words.get("lang.name", path.stem)})
    return tuple(sorted(found, key=lambda one: (one["code"] != PLAIN, one["name"])))


@dataclass(frozen=True)
class Tongue:
    """One language. Knows its own words and falls back on English for the rest."""

    code: str
    words: dict
    plain: dict

    @classmethod
    def of(cls, code: str = PLAIN) -> "Tongue":
        code = code if _read(code) else PLAIN
        return cls(code, _read(code), _read(PLAIN))

    @classmethod
    def asked(cls, wanted: str = "", header: str = "") -> "Tongue":
        """Which language was asked for: `?lang=` wins, then the browser's own list."""
        for code in [wanted] + cls.listed(header):
            if code and _read(code):
                return cls.of(code)
        return cls.of(PLAIN)

    @staticmethod
    def listed(header: str) -> list:
        """`Accept-Language: ru-RU,ru;q=0.9,en;q=0.8` → ['ru', 'ru', 'en'], best first."""
        weighted = []
        for part in (header or "").split(","):
            name, _, rest = part.strip().partition(";")
            name = name.strip().lower().partition("-")[0]
            weight = 1.0
            if rest.strip().startswith("q="):
                try:
                    weight = float(rest.strip()[2:])
                except ValueError:
                    weight = 0.0
            if name and name != "*":
                weighted.append((-weight, len(weighted), name))
        return [name for _, _, name in sorted(weighted)]

    def has(self, key: str) -> bool:
        return key in self.words or key in self.plain

    def say(self, key: str, **parts) -> str:
        """The phrase behind a key, with its holes filled.

        An unknown key comes back as itself rather than as an empty space: a missing word
        should be visible and fixable, not silently swallowed."""
        text = self.words.get(key) or self.plain.get(key) or key
        return HOLE.sub(lambda hole: str(parts.get(hole.group(1), hole.group(0))), text)

    def tell(self, said) -> str:
        """A phrase the map put together earlier.

        It may be a `Said`, the same thing read back from a file as a plain dictionary, or
        text that was never a phrase at all — an address, a number — which stands as it is."""
        if isinstance(said, Said):
            return said.by(self)
        if isinstance(said, dict) and "key" in said:
            return Said.of(said["key"], **said.get("parts", {})).by(self)
        return "" if said is None else str(said)


@dataclass(frozen=True)
class Said:
    """A phrase the map decided on before it knew the language: a key and what to fill in.

    Everything inside the map travels in this shape, and only turns into words at the edge —
    in the payload for the page, or in the text for the reader."""

    key: str
    parts: tuple = ()

    @classmethod
    def of(cls, key: str, **parts) -> "Said":
        return cls(key, tuple(sorted(parts.items())))

    def by(self, tongue: Tongue) -> str:
        """Holes can hold other phrases: a reason inside a reason is still one sentence."""
        return tongue.say(self.key, **{name: tongue.tell(value) for name, value in self.parts})

    def payload(self) -> dict:
        """The phrase as plain JSON, for a file that outlives the run that wrote it."""
        return {"key": self.key,
                "parts": {name: value.payload() if isinstance(value, Said) else value
                          for name, value in self.parts}}

"""The layout: where on the map a castle, the customs house or a balloon stands.

The layout is made by a human with a mouse, and it is shared by everyone who opens the map.
So it lives on the server next to the snapshot, not in a browser: otherwise everyone would
have a map of their own.

The layout changes no facts: no coordinate can widen a road or hand a castle to someone else.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from .tongue import Said


class LayoutError(ValueError):
    """A layout we cannot accept: not numbers, a strange name, or off the edge of the map."""

    def __init__(self, said: Said):
        super().__init__(said.key)
        self.said = said


@dataclass(frozen=True)
class Layout:
    #: a thing's name (castle key, "router", device key) → [x, y]
    places: dict
    #: castle key → how it looks: whether the yard is folded, how houses are sorted, how many columns
    looks: dict = field(default_factory=dict)
    #: The size of the island [width, height]. Empty means the map takes its usual one.
    field_size: list = field(default_factory=list)

    #: The map is large but not endless: past these bounds a thing can no longer be found.
    FIELD = 4000

    @classmethod
    def read(cls, path) -> "Layout":
        path = Path(path)
        if not path.is_file():
            return cls({})
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LayoutError(Said.of("layout.unreadable", why=str(error))) from error
        return cls(cls.checked(payload.get("places", {})), cls.checked_looks(payload.get("looks", {})),
                   cls.checked_field(payload.get("field", [])))

    #: What the two ends used to be called, in a layout written by an older map. Renaming them
    #: must not move the customs house and the pier back into the middle of the island.
    PLACES_WAS: ClassVar[dict] = {"\u0440\u043e\u0443\u0442\u0435\u0440": "router",
                                  "\u0438\u043d\u0442\u0435\u0440\u043d\u0435\u0442": "internet"}

    @classmethod
    def checked(cls, places) -> dict:
        if not isinstance(places, dict):
            raise LayoutError(Said.of("layout.want-places"))
        if len(places) > 500:
            raise LayoutError(Said.of("layout.too-many-places"))
        found = {}
        for name, place in places.items():
            name = cls.PLACES_WAS.get(name, name)
            if not isinstance(name, str) or not name or len(name) > 128:
                raise LayoutError(Said.of("layout.odd-place-name", name=repr(name)))
            if not isinstance(place, (list, tuple)) or len(place) != 2:
                raise LayoutError(Said.of("layout.want-xy", name=name))
            spot = []
            for number in place:
                if isinstance(number, bool) or not isinstance(number, (int, float)):
                    raise LayoutError(Said.of("layout.not-a-number", name=name))
                if not -cls.FIELD <= number <= cls.FIELD:
                    raise LayoutError(Said.of("layout.off-the-edge", name=name))
                spot.append(round(float(number), 1))
            found[name] = spot
        return found

    #: How houses are laid out in a yard. The map knows no other ways.
    SORTS = ("as-is", "name", "address", "kind")
    #: What those ways used to be called, in a layout written by an older map.
    SORTS_WAS = {"\u043a\u0430\u043a \u0435\u0441\u0442\u044c": "as-is",
                 "\u043f\u043e \u0438\u043c\u0435\u043d\u0438": "name",
                 "\u043f\u043e \u0430\u0434\u0440\u0435\u0441\u0443": "address",
                 "\u043f\u043e \u0432\u0438\u0434\u0443": "kind"}

    @classmethod
    def checked_looks(cls, looks) -> dict:
        """How a yard looks: folded or not, sorted by what, in how many columns."""
        if not isinstance(looks, dict):
            raise LayoutError(Said.of("layout.want-looks"))
        if len(looks) > 64:
            raise LayoutError(Said.of("layout.too-many-castles"))
        found = {}
        for name, look in looks.items():
            if not isinstance(name, str) or not name or len(name) > 128:
                raise LayoutError(Said.of("layout.odd-castle-name", name=repr(name)))
            if not isinstance(look, dict):
                raise LayoutError(Said.of("layout.want-look", name=name))
            kept = {}
            if "folded" in look:
                if not isinstance(look["folded"], bool):
                    raise LayoutError(Said.of("layout.folded-yes-no", name=name))
                kept["folded"] = look["folded"]
            if "sort" in look:
                sort = cls.SORTS_WAS.get(look["sort"], look["sort"])
                if sort not in cls.SORTS:
                    raise LayoutError(Said.of("layout.no-such-sort", name=name))
                kept["sort"] = sort
            if "columns" in look:
                columns = look["columns"]
                if isinstance(columns, bool) or not isinstance(columns, int) or not 0 <= columns <= 8:
                    raise LayoutError(Said.of("layout.columns-range", name=name))
                kept["columns"] = columns
            if kept:
                found[name] = kept
        return found

    #: Smaller cannot be made out, larger has nowhere to go: an island is not a continent.
    ISLAND = {"least": (700, 500), "most": (3600, 2600)}

    @classmethod
    def checked_field(cls, size) -> list:
        """The island's size. Empty means the usual one; otherwise two sensible numbers."""
        if not size:
            return []
        if not isinstance(size, (list, tuple)) or len(size) != 2:
            raise LayoutError(Said.of("layout.want-size"))
        found = []
        for number, least, most in zip(size, cls.ISLAND["least"], cls.ISLAND["most"]):
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise LayoutError(Said.of("layout.size-numbers"))
            if not least <= number <= most:
                raise LayoutError(Said.of("layout.size-range", least=least, most=most))
            found.append(round(float(number)))
        return found

    def write(self, path) -> None:
        """Written through a temporary file: an interrupted write leaves no half-layout."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".layout-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump({"places": self.places, "looks": self.looks, "field": self.field_size},
                          file, ensure_ascii=False, indent=1)
                file.write("\n")
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def payload(self) -> dict:
        return {"places": self.places, "looks": self.looks, "field": self.field_size}

"""Pictures of devices: the page draws them, and Python only knows which kinds exist.

One picture is described in exactly one place — web/sprites.json. There is no second draughtsman
here: otherwise the same grid would live in two places and the two would drift apart.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SPRITES = Path(__file__).resolve().parent.parent / "web" / "sprites.json"


@dataclass(frozen=True)
class Sprites:
    palette: dict
    icons: dict
    fallback: str

    @classmethod
    def read(cls, path: Path = SPRITES) -> "Sprites":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(payload["palette"], payload["icons"], payload["default"])

    @property
    def kinds(self) -> tuple:
        return tuple(self.icons)

    def has(self, kind: str) -> bool:
        return kind in self.icons

    def unknown(self, kinds) -> tuple:
        """Kinds that are not in the set: the map draws a house and says so in the journal."""
        return tuple(sorted({kind for kind in kinds if kind and not self.has(kind)}))

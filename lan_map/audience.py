"""Who is shown the map: a list of networks that can be changed by tick boxes on the map itself.

By default the list comes from the environment — that is how compose sets it. Once a human has
chosen their own, it lies next to the snapshot and takes precedence from then on: the map's
settings live where its data lives, and outlive a rebuild of the container.

This is a setting of the map, not of the network: it never touches the router. But you cannot
shut yourself out — there would be nobody left to tick the box back.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from pathlib import Path

from .tongue import Said


class AudienceError(ValueError):
    """A list we cannot accept: not networks, too long, or it shuts the chooser out."""

    def __init__(self, said: Said):
        super().__init__(said.key)
        self.said = said


@dataclass(frozen=True)
class Audience:
    #: What the environment set: this is where the map starts its life.
    default: tuple
    path: Path
    MOST = 16

    def networks(self) -> tuple:
        """The networks the map is visible to. No file, or a broken one, means the default."""
        path = Path(self.path)
        if not path.is_file():
            return self.default
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return tuple(ip_network(text, strict=False) for text in payload.get("show", []))
        except (OSError, ValueError):
            return self.default

    def choose(self, texts, keeper: str) -> tuple:
        """A new list. `keeper` is the address of whoever chooses: they cannot shut themselves out."""
        if not isinstance(texts, list) or not texts:
            raise AudienceError(Said.of("watchers.empty"))
        if len(texts) > self.MOST:
            raise AudienceError(Said.of("watchers.too-many"))
        chosen = []
        for text in texts:
            if not isinstance(text, str):
                raise AudienceError(Said.of("watchers.not-a-string"))
            try:
                chosen.append(ip_network(text, strict=False))
            except ValueError as error:
                raise AudienceError(Said.of("watchers.not-a-network", text=text)) from error
        self.keep(chosen, keeper)
        self.write(chosen)
        return tuple(chosen)

    @staticmethod
    def keep(chosen, keeper: str) -> None:
        try:
            watcher = ip_address(keeper)
        except ValueError as error:
            raise AudienceError(Said.of("watchers.who-chooses")) from error
        if not any(watcher.version == network.version and watcher in network for network in chosen):
            raise AudienceError(Said.of("watchers.locks-you-out", keeper=keeper))

    def write(self, chosen) -> None:
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump({"show": [str(network) for network in chosen]}, file, ensure_ascii=False, indent=1)
                file.write("\n")
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

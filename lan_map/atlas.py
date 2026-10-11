"""The atlas: what the owner knows about the network and the router does not.

The router gives facts: addresses, leases, rules. The atlas gives names and looks: what a
castle is called, what the machine on a static address is called, which networks are ours and
which picture to draw a device with. Where things stand is not here: the map remembers that
itself, when a thing is dragged.

The split matters. Everything that came from the router refreshes by itself; everything in
the atlas is changed by a human. No line of the atlas can overrule a fact — only name it.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True)
class Atlas:
    #: segment interface → {title, trusted}
    segments: dict = field(default_factory=dict)
    #: device address or MAC → {name, kind}; kind names a picture in web/sprites.json
    devices: dict = field(default_factory=dict)
    #: groups of addresses belonging to one device: the map joins them into one house
    same: tuple = ()
    #: what sits on a port and why it is open, by place and port: "router udp 53" → "DNS". The
    #: place is "router" for any of the router's own addresses, otherwise an address or a
    #: network as a line of access writes it ("192.168.20.10", "192.168.20.x").
    ports: dict = field(default_factory=dict)

    #: What kinds used to be called, before they became codes. An atlas written by an older
    #: map is still the owner's work: it is read, not thrown away.
    WAS: ClassVar[dict] = {
        "\u0434\u043e\u043c": "house", "NAS": "nas", "\u0441\u0435\u0440\u0432\u0435\u0440": "server",
        "\u043d\u043e\u0443\u0442\u0431\u0443\u043a": "laptop",
        "\u0442\u0435\u043b\u0435\u0444\u043e\u043d": "phone",
        "\u043f\u043b\u0430\u043d\u0448\u0435\u0442": "tablet",
        "\u0442\u0435\u043b\u0435\u0432\u0438\u0437\u043e\u0440": "tv",
        "\u043f\u0440\u0438\u043d\u0442\u0435\u0440": "printer",
        "\u043f\u0440\u0438\u0441\u0442\u0430\u0432\u043a\u0430": "console",
        "\u0418\u0411\u041f": "ups", "\u043a\u0430\u043c\u0435\u0440\u0430": "camera",
        "\u043a\u043e\u043b\u043e\u043d\u043a\u0430": "speaker", "Wi-Fi": "wifi",
        "\u0447\u0430\u0441\u044b": "watch", "\u043f\u043b\u0430\u0442\u0430": "board",
        "\u0440\u043e\u0443\u0442\u0435\u0440": "router",
        "\u043a\u043e\u043c\u043c\u0443\u0442\u0430\u0442\u043e\u0440": "switch",
        "\u043b\u0430\u043c\u043f\u0430": "lamp",
        "\u043f\u044b\u043b\u0435\u0441\u043e\u0441": "vacuum",
        "\u0440\u043e\u0437\u0435\u0442\u043a\u0430": "socket",
        "\u0434\u0430\u0442\u0447\u0438\u043a": "sensor",
        "\u0442\u0435\u0440\u043c\u043e\u0441\u0442\u0430\u0442": "thermostat",
        "\u0437\u0432\u043e\u043d\u043e\u043a": "doorbell", "Apple TV": "apple-tv",
        "Mac mini": "mac-mini", "Mac Studio": "mac-studio", "\u0445\u0430\u0431": "hub",
        "\u043f\u043e\u0434\u043e\u0437\u0440\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0439": "suspicious",
        "\u0440\u043e\u0431\u043e\u0442": "robot", "\u0430\u0433\u0435\u043d\u0442": "agent",
        "\u0418\u0418": "ai", "OpenClaw": "openclaw", "Hermes": "hermes",
        "iPhone": "iphone", "Android": "android",
    }

    @classmethod
    def empty(cls) -> "Atlas":
        return cls()

    @classmethod
    def read(cls, path: Path) -> "Atlas":
        """There may be no atlas: then names come only from what the router knows."""
        path = Path(path)
        if not path.is_file():
            return cls.empty()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(segments=payload.get("segments", {}),
                   devices={key: cls.catch_up(entry)
                            for key, entry in payload.get("devices", {}).items()},
                   same=tuple(tuple(group) for group in payload.get("same", ())),
                   ports=dict(payload.get("ports", {})))

    @classmethod
    def catch_up(cls, entry: dict) -> dict:
        """One device's record, with a kind from an older map turned into today's code."""
        kind = entry.get("kind")
        return {**entry, "kind": cls.WAS[kind]} if kind in cls.WAS else entry

    def title(self, interface: str) -> str:
        """A castle's name. With no atlas it is called after its interface — which is honest."""
        return self.segments.get(interface, {}).get("title", interface)

    def trusted(self, interface: str) -> bool:
        """One of ours. A road open out of it is a decision, not a discovery."""
        return bool(self.segments.get(interface, {}).get("trusted", False))

    def device(self, *keys: str) -> dict:
        """A device's record, by any of its keys: an address or a MAC."""
        for key in keys:
            if key and key in self.devices:
                return self.devices[key]
        return {}

    def with_segment(self, key: str, **fields) -> "Atlas":
        """The atlas with a castle renamed or recoloured. An empty value removes the field."""
        segments = {name: dict(entry) for name, entry in self.segments.items()}
        entry = segments.get(key, {})
        for name, value in fields.items():
            if value:
                entry[name] = value
            else:
                entry.pop(name, None)
        if entry:
            segments[key] = entry
        else:
            segments.pop(key, None)
        return replace(self, segments=segments)

    def with_device(self, key: str, **fields) -> "Atlas":
        """The atlas with a device's record changed. An empty value removes a field, not fills it."""
        devices = {name: dict(entry) for name, entry in self.devices.items()}
        entry = devices.get(key, {})
        for name, value in fields.items():
            if value:
                entry[name] = value
            else:
                entry.pop(name, None)
        if entry:
            devices[key] = entry
        else:
            devices.pop(key, None)
        return replace(self, devices=devices)

    def with_port(self, key: str, note: str) -> "Atlas":
        """The atlas with what a port is for written down. An empty note removes the line."""
        ports = dict(self.ports)
        if note:
            ports[key] = note
        else:
            ports.pop(key, None)
        return replace(self, ports=ports)

    def write(self, path) -> None:
        """Written through a temporary file: an interrupted write leaves no half-atlas."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".atlas-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump({"segments": self.segments, "devices": self.devices,
                           "same": [list(group) for group in self.same], "ports": self.ports},
                          file, ensure_ascii=False, indent=1)
                file.write("\n")
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def joined(self, key: str) -> tuple:
        """The addresses the owner declared to be one device together with this one."""
        for group in self.same:
            if key in group:
                return group
        return ()

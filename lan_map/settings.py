"""Settings, read from the environment once.

The environment is handed in rather than read from os.environ here: tests build settings out
of an ordinary dictionary, and nothing else in the program looks at the environment at all.

The router's password is never kept in the repository. It arrives as a variable, or it lies in
a file next to the owner's home directory — and the path to that file is the setting.
"""
from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_network
from pathlib import Path
from typing import ClassVar, Mapping

from .tongue import Said


class SettingsError(RuntimeError):
    """Without this setting nothing works, and there is nothing to guess it from."""

    def __init__(self, said: Said):
        super().__init__(said.key)
        self.said = said


@dataclass(frozen=True)
class Settings:
    router_host: str
    router_user: str
    router_password: str
    router_cert: Path
    data_dir: Path
    host: str
    port: int
    #: How often to take a snapshot unasked. Zero means by button only.
    refresh_minutes: int
    #: How often to look into the router's DNS cache for names. Zero means never.
    names_minutes: int
    #: Who is shown the map, and who may move things on it.
    show: tuple
    move: tuple
    deny: tuple
    trusted_proxies: tuple

    PREFIX: ClassVar[str] = "LAN_MAP_"

    @classmethod
    def from_env(cls, env: Mapping[str, str], base: Path, need_password: bool = True) -> "Settings":
        """Only whoever goes to the router needs the password. The page lives on an old snapshot."""
        def read(name: str, default: str) -> str:
            return env.get(cls.PREFIX + name, default)

        try:
            password = cls.password(env)
        except SettingsError:
            if need_password:
                raise
            password = ""
        return cls(
            router_host=read("ROUTER_HOST", "192.168.88.1"),
            router_user=read("ROUTER_USER", "lan-map"),
            router_password=password,
            router_cert=Path(read("ROUTER_CERT", str(base / "config" / "router-cert.pem"))),
            data_dir=Path(read("DATA_DIR", str(base / "data"))),
            host=read("HOST", "127.0.0.1"),
            port=cls.number(read("PORT", "8080"), "PORT"),
            refresh_minutes=cls.minutes(read("REFRESH_MINUTES", "0"), "REFRESH_MINUTES"),
            names_minutes=cls.minutes(read("NAMES_MINUTES", "0"), "NAMES_MINUTES"),
            show=cls.networks(read("SHOW_NETWORKS", "192.168.88.0/24,192.168.20.0/24"), "SHOW_NETWORKS"),
            move=cls.networks(read("MOVE_NETWORKS", "192.168.88.0/24"), "MOVE_NETWORKS"),
            deny=cls.networks(read("MOVE_DENY", "192.168.88.1/32"), "MOVE_DENY"),
            trusted_proxies=cls.networks(read("TRUSTED_PROXIES", "127.0.0.0/8"), "TRUSTED_PROXIES"),
        )

    @classmethod
    def number(cls, text: str, name: str) -> int:
        if not text.isdigit() or not 1 <= int(text) <= 65535:
            raise SettingsError(Said.of("settings.want-port", name=cls.PREFIX + name, text=text))
        return int(text)

    @classmethod
    def minutes(cls, text: str, name: str) -> int:
        if not text.strip().isdigit():
            raise SettingsError(Said.of("settings.want-minutes", name=cls.PREFIX + name, text=text))
        return int(text)

    @classmethod
    def networks(cls, text: str, name: str) -> tuple:
        found = []
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                found.append(ip_network(part, strict=False))
            except ValueError as error:
                raise SettingsError(Said.of("settings.not-a-network",
                                            name=cls.PREFIX + name, text=part)) from error
        return tuple(found)

    @classmethod
    def password(cls, env: Mapping[str, str]) -> str:
        """The password from a variable or a file. An empty password is no password, not one."""
        direct = env.get(cls.PREFIX + "ROUTER_PASSWORD", "")
        if direct:
            return direct
        where = env.get(cls.PREFIX + "ROUTER_PASSWORD_FILE", "")
        if not where:
            raise SettingsError(Said.of("settings.no-password"))
        try:
            text = Path(where).read_text(encoding="utf-8")
        except OSError as err:
            raise SettingsError(Said.of("settings.password-unreadable", where=where,
                                        why=err.strerror or err)) from err
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(cls.PREFIX + "ROUTER_PASSWORD="):
                line = line.split("=", 1)[1]
            elif not line or line.startswith("#"):
                continue
            if line:
                return line
        raise SettingsError(Said.of("settings.password-file-empty", where=where))

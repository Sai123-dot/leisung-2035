"""Where the client certificate and remembered TVs live on disk."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ENV_HOME = "HISENSE_REMOTE_HOME"
DEFAULT_CLIENT_NAME = "Hisense Remote"


def default_config_dir() -> Path:
    """``$HISENSE_REMOTE_HOME``, else ``$XDG_CONFIG_HOME/hisense-remote``, else ``~/.config/hisense-remote``."""
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "hisense-remote"


class ConfigStore:
    """Persistent client certificate plus a small JSON file of known TVs."""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = Path(root).expanduser() if root else default_config_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        self.cert_path = str(self.root / "client.crt")
        self.key_path = str(self.root / "client.key")
        self.config_path = self.root / "config.json"

    # ---- raw file access -------------------------------------------------

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("default_host", None)
        data.setdefault("tvs", {})
        if not isinstance(data["tvs"], dict):
            data["tvs"] = {}
        return data

    def save(self, data: dict[str, Any]) -> None:
        tmp = self.config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.config_path)

    # ---- convenience -----------------------------------------------------

    def has_certificate(self) -> bool:
        return os.path.isfile(self.cert_path) and os.path.isfile(self.key_path)

    @property
    def default_host(self) -> str | None:
        return self.load()["default_host"]

    @default_host.setter
    def default_host(self, host: str | None) -> None:
        data = self.load()
        data["default_host"] = host
        self.save(data)

    @property
    def tvs(self) -> dict[str, dict[str, Any]]:
        return self.load()["tvs"]

    def remember_tv(self, host: str, **info: Any) -> None:
        """Merge non-empty ``info`` into the record for ``host`` and make it the default if none is set."""
        data = self.load()
        entry = data["tvs"].setdefault(host, {})
        for key, value in info.items():
            if value not in (None, ""):
                entry[key] = value
        if not data["default_host"]:
            data["default_host"] = host
        self.save(data)

    def forget_tv(self, host: str) -> None:
        data = self.load()
        data["tvs"].pop(host, None)
        if data["default_host"] == host:
            data["default_host"] = next(iter(data["tvs"]), None)
        self.save(data)

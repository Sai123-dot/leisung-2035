"""An in-memory TV used by ``serve --demo`` and the tests."""

from __future__ import annotations

from typing import Any

from .apps import app_name
from .keys import resolve_direction, resolve_key
from .tv import (
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_NEEDS_PAIRING,
    STATUS_PAIRING,
    Listener,
    NotConnected,
    PairingFailed,
    TVError,
)

LAUNCHER = "com.google.android.tvlauncher"


class FakeTV:
    """Behaves like a paired, connected Hisense TV without any network."""

    def __init__(self, host: str = "192.168.1.50", name: str = "Demo Hisense TV") -> None:
        self.host: str | None = host
        self.name = name
        self.mac = "00:11:22:33:44:55"
        self.status = STATUS_CONNECTED
        self.error: str | None = None
        self.is_on = True
        self.current_app = LAUNCHER
        self.volume = {"level": 12, "max": 100, "muted": False}
        self.pair_code = "123456"
        self.sent: list[tuple[int | str, str]] = []
        self.texts: list[str] = []
        self.apps: list[str] = []
        self.woken = 0
        self._listeners: list[Listener] = []

    # ---- state -----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        live = self.status == STATUS_CONNECTED
        return {
            "host": self.host,
            "name": self.name,
            "mac": self.mac,
            "status": self.status,
            "error": self.error,
            "available": live,
            "needs_pairing": self.status == STATUS_NEEDS_PAIRING,
            "is_on": self.is_on if live else None,
            "current_app": self.current_app if live else None,
            "current_app_name": app_name(self.current_app) if live else None,
            "volume": dict(self.volume) if live else None,
            "device": {"manufacturer": "Hisense", "model": "Demo", "sw_version": "demo"},
        }

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self) -> None:
        snap = self.snapshot()
        for listener in list(self._listeners):
            listener(snap)

    # ---- connection ------------------------------------------------------

    async def connect(self, host: str | None = None) -> dict[str, Any]:
        if host:
            self.host = host.strip()
        self.status = STATUS_CONNECTED
        self.error = None
        self._notify()
        return self.snapshot()

    def start_background_connect(self) -> None:
        self.status = STATUS_CONNECTED
        self.error = None

    async def disconnect(self) -> None:
        self.status = STATUS_DISCONNECTED
        self._notify()

    async def start_pairing(self, host: str | None = None) -> dict[str, Any]:
        if host:
            self.host = host.strip()
        self.status = STATUS_PAIRING
        self.error = None
        self._notify()
        return self.snapshot()

    async def finish_pairing(self, code: str) -> dict[str, Any]:
        if self.status != STATUS_PAIRING:
            raise TVError("Pairing has not been started")
        if (code or "").strip().upper() != self.pair_code:
            self.status = STATUS_NEEDS_PAIRING
            self.error = "Pairing failed: wrong code"
            self._notify()
            raise PairingFailed(self.error)
        return await self.connect()

    # ---- commands --------------------------------------------------------

    def _require_connected(self) -> None:
        if self.status != STATUS_CONNECTED:
            raise NotConnected(f"Not connected to the TV (status: {self.status})")

    def send_key(self, key: int | str, direction: str = "SHORT") -> None:
        code = resolve_key(key)
        direction = resolve_direction(direction)
        self._require_connected()
        self.sent.append((code, direction))
        if direction == "START_LONG":
            return
        if code in ("KEYCODE_POWER", "KEYCODE_TV_POWER"):
            self.is_on = not self.is_on
        elif code == "KEYCODE_WAKEUP":
            self.is_on = True
        elif code == "KEYCODE_SLEEP":
            self.is_on = False
        elif code == "KEYCODE_VOLUME_UP":
            self.volume["level"] = min(self.volume["max"], self.volume["level"] + 1)
            self.volume["muted"] = False
        elif code == "KEYCODE_VOLUME_DOWN":
            self.volume["level"] = max(0, self.volume["level"] - 1)
        elif code in ("KEYCODE_VOLUME_MUTE", "KEYCODE_MUTE"):
            self.volume["muted"] = not self.volume["muted"]
        elif code == "KEYCODE_HOME":
            self.current_app = LAUNCHER
        self._notify()

    def send_text(self, text: str) -> None:
        self._require_connected()
        self.texts.append(text)

    def launch_app(self, app: str) -> None:
        self._require_connected()
        self.apps.append(app)
        self.current_app = app
        self._notify()

    async def wake(self) -> bool:
        self.woken += 1
        self.is_on = True
        self._notify()
        return True

"""Connection, pairing and command layer on top of ``androidtvremote2``."""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any, Callable, Protocol

from androidtvremote2 import AndroidTVRemote, CannotConnect, ConnectionClosed, InvalidAuth

from .apps import app_name
from .config import DEFAULT_CLIENT_NAME, ConfigStore
from .keys import resolve_direction, resolve_key

LOGGER = logging.getLogger(__name__)

API_PORT = 6466
PAIR_PORT = 6467

STATUS_DISCONNECTED = "disconnected"
STATUS_CONNECTING = "connecting"
STATUS_CONNECTED = "connected"
STATUS_RECONNECTING = "reconnecting"
STATUS_UNREACHABLE = "unreachable"
STATUS_NEEDS_PAIRING = "needs_pairing"
STATUS_PAIRING = "pairing"

Listener = Callable[[dict[str, Any]], None]


class TVError(Exception):
    """Base class for errors talking to the TV."""


class NeedsPairing(TVError):
    """The TV has not accepted our client certificate yet."""


class NotConnected(TVError):
    """A command was sent while there is no live connection."""


class TVUnreachable(TVError):
    """The TV could not be reached on the network."""


class PairingFailed(TVError):
    """Pairing was rejected or cancelled."""


class TVController(Protocol):
    """What the web server and CLI need from a TV implementation."""

    host: str | None

    def snapshot(self) -> dict[str, Any]: ...
    def add_listener(self, listener: Listener) -> None: ...
    def remove_listener(self, listener: Listener) -> None: ...
    async def connect(self, host: str | None = None) -> dict[str, Any]: ...
    def start_background_connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def start_pairing(self, host: str | None = None) -> dict[str, Any]: ...
    async def finish_pairing(self, code: str) -> dict[str, Any]: ...
    def send_key(self, key: int | str, direction: str = "SHORT") -> None: ...
    def send_text(self, text: str) -> None: ...
    def launch_app(self, app: str) -> None: ...
    async def wake(self) -> bool: ...


# ---- Wake-on-LAN -----------------------------------------------------------


def magic_packet(mac: str) -> bytes:
    """Build a Wake-on-LAN magic packet for ``mac`` (any common separator accepted)."""
    clean = "".join(ch for ch in mac if ch.isalnum())
    if len(clean) != 12:
        raise ValueError(f"Invalid MAC address: {mac!r}")
    return b"\xff" * 6 + bytes.fromhex(clean) * 16


def send_magic_packet(mac: str, host: str | None = None, port: int = 9) -> None:
    """Broadcast a magic packet, and also send it straight to ``host`` when known."""
    payload = magic_packet(mac)
    targets = ["255.255.255.255"]
    if host:
        targets.append(host)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in targets:
            try:
                sock.sendto(payload, (target, port))
            except OSError as exc:
                LOGGER.debug("Wake-on-LAN packet to %s failed: %s", target, exc)


# ---- The real thing --------------------------------------------------------


class HisenseTV:
    """One Hisense Android TV: pairing, a self-healing connection, and commands."""

    def __init__(
        self,
        store: ConfigStore,
        host: str | None = None,
        *,
        client_name: str = DEFAULT_CLIENT_NAME,
        enable_ime: bool = True,
        api_port: int = API_PORT,
        pair_port: int = PAIR_PORT,
    ) -> None:
        self._store = store
        self._client_name = client_name
        self._enable_ime = enable_ime
        self._api_port = api_port
        self._pair_port = pair_port
        self._remote: AndroidTVRemote | None = None
        self._connect_task: asyncio.Task[None] | None = None
        self._listeners: list[Listener] = []
        self._status = STATUS_DISCONNECTED
        self._error: str | None = None
        self._available = False
        self.name: str | None = None
        self.mac: str | None = None
        self.host: str | None = None
        self._set_host(host or store.default_host)

    # ---- state -----------------------------------------------------------

    @property
    def status(self) -> str:
        return self._status

    def snapshot(self) -> dict[str, Any]:
        remote = self._remote
        live = remote is not None and self._status == STATUS_CONNECTED
        volume = dict(remote.volume_info) if live and remote.volume_info else None
        device = dict(remote.device_info) if remote and remote.device_info else None
        current_app = (remote.current_app or None) if live else None
        name = self.name
        if not name and device and device.get("model"):
            name = f"{device.get('manufacturer', '')} {device['model']}".strip()
        return {
            "host": self.host,
            "name": name,
            "mac": self.mac,
            "status": self._status,
            "error": self._error,
            "available": self._available,
            "needs_pairing": self._status == STATUS_NEEDS_PAIRING,
            "is_on": (remote.is_on if live else None),
            "current_app": current_app,
            "current_app_name": app_name(current_app),
            "volume": volume,
            "device": device,
        }

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self) -> None:
        snap = self.snapshot()
        for listener in list(self._listeners):
            try:
                listener(snap)
            except Exception:  # noqa: BLE001 - a bad listener must not break the TV link
                LOGGER.exception("TV state listener failed")

    def _set_status(self, status: str, error: str | None = None) -> None:
        self._status = status
        self._error = error
        self._notify()

    def _set_host(self, host: str | None) -> None:
        self.host = host.strip() if host else None
        known = self._store.tvs.get(self.host, {}) if self.host else {}
        self.name = known.get("name")
        self.mac = known.get("mac")

    # ---- connection ------------------------------------------------------

    def _build_remote(self) -> AndroidTVRemote:
        assert self.host
        remote = AndroidTVRemote(
            self._client_name,
            self._store.cert_path,
            self._store.key_path,
            self.host,
            api_port=self._api_port,
            pair_port=self._pair_port,
            enable_ime=self._enable_ime,
        )
        remote.add_is_on_updated_callback(lambda _value: self._notify())
        remote.add_current_app_updated_callback(lambda _value: self._notify())
        remote.add_volume_info_updated_callback(lambda _value: self._notify())
        remote.add_is_available_updated_callback(self._on_available)
        return remote

    def _on_available(self, available: bool) -> None:
        self._available = available
        if available:
            self._set_status(STATUS_CONNECTED)
        else:
            self._set_status(STATUS_RECONNECTING, "Connection lost, reconnecting")

    def _on_invalid_auth(self) -> None:
        self._available = False
        self._set_status(STATUS_NEEDS_PAIRING, "The TV no longer accepts this client. Pair again.")

    async def connect(self, host: str | None = None) -> dict[str, Any]:
        """Open the command channel. Raises NeedsPairing or TVUnreachable."""
        if host:
            self._set_host(host)
        if not self.host:
            raise TVError("No TV address configured. Run discovery or pass --host.")
        await self.disconnect()
        remote = self._build_remote()
        await remote.async_generate_cert_if_missing()
        self._remote = remote
        self._set_status(STATUS_CONNECTING)
        try:
            await remote.async_connect()
        except InvalidAuth as exc:
            self._set_status(STATUS_NEEDS_PAIRING, "Not paired with this TV yet")
            raise NeedsPairing(f"{self.host} needs pairing first") from exc
        except CannotConnect as exc:
            msg = f"Could not reach {self.host}:{self._api_port}. Is the TV on the same network?"
            self._set_status(STATUS_UNREACHABLE, msg)
            raise TVUnreachable(msg) from exc
        except ConnectionClosed as exc:
            msg = f"{self.host} closed the connection before the remote started"
            self._set_status(STATUS_UNREACHABLE, msg)
            raise TVUnreachable(msg) from exc

        remote.keep_reconnecting(self._on_invalid_auth)
        self._available = True
        info = remote.device_info or {}
        if not self.name and info.get("model"):
            self.name = f"{info.get('manufacturer', '')} {info['model']}".strip()
        self._store.remember_tv(
            self.host,
            name=self.name,
            mac=self.mac,
            manufacturer=info.get("manufacturer"),
            model=info.get("model"),
            sw_version=info.get("sw_version"),
        )
        self._store.default_host = self.host
        self._set_status(STATUS_CONNECTED)
        return self.snapshot()

    def start_background_connect(self, retry_delay: float = 5.0) -> None:
        """Connect now and keep retrying in the background until it works or pairing is needed."""
        if self._connect_task and not self._connect_task.done():
            return
        self._connect_task = asyncio.get_running_loop().create_task(self._connect_loop(retry_delay))

    async def _connect_loop(self, retry_delay: float) -> None:
        delay = retry_delay
        while True:
            try:
                await self.connect()
                return
            except NeedsPairing:
                return
            except TVError as exc:
                LOGGER.info("%s; retrying in %.0f s", exc, delay)
            except Exception:  # noqa: BLE001 - keep the server alive and keep trying
                LOGGER.exception("Unexpected error connecting to %s; retrying in %.0f s", self.host, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def disconnect(self) -> None:
        task = self._connect_task
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            self._connect_task = None
        if self._remote:
            self._remote.disconnect()
            self._remote = None
        self._available = False
        if self._status != STATUS_DISCONNECTED:
            self._set_status(STATUS_DISCONNECTED)

    # ---- pairing ---------------------------------------------------------

    async def start_pairing(self, host: str | None = None) -> dict[str, Any]:
        """Ask the TV to show a pairing code. Follow with ``finish_pairing``."""
        if host:
            self._set_host(host)
        if not self.host:
            raise TVError("No TV address configured. Run discovery or pass --host.")
        await self.disconnect()
        remote = self._build_remote()
        await remote.async_generate_cert_if_missing()
        self._remote = remote
        self._set_status(STATUS_PAIRING)
        try:
            self.name, self.mac = await remote.async_get_name_and_mac()
        except Exception as exc:  # noqa: BLE001 - purely informational
            LOGGER.debug("Could not read the TV certificate details: %s", exc)
        try:
            await remote.async_start_pairing()
        except CannotConnect as exc:
            msg = f"Could not reach {self.host}:{self._pair_port} for pairing"
            self._set_status(STATUS_UNREACHABLE, msg)
            raise TVUnreachable(msg) from exc
        except ConnectionClosed as exc:
            msg = "The TV did not answer the pairing request"
            self._set_status(STATUS_NEEDS_PAIRING, msg)
            raise PairingFailed(msg) from exc
        self._notify()
        return self.snapshot()

    async def finish_pairing(self, code: str) -> dict[str, Any]:
        """Send the code shown on the TV, then connect."""
        if not self._remote or self._status != STATUS_PAIRING:
            raise TVError("Pairing has not been started")
        code = (code or "").strip().upper()
        try:
            await self._remote.async_finish_pairing(code)
        except InvalidAuth as exc:
            self._set_status(STATUS_NEEDS_PAIRING, f"Pairing failed: {exc}")
            raise PairingFailed(f"Pairing failed: {exc}") from exc
        except ConnectionClosed as exc:
            self._set_status(STATUS_NEEDS_PAIRING, "The TV cancelled pairing")
            raise PairingFailed("The TV cancelled pairing") from exc
        assert self.host
        self._store.remember_tv(self.host, name=self.name, mac=self.mac)
        return await self.connect()

    # ---- commands --------------------------------------------------------

    def _require_remote(self) -> AndroidTVRemote:
        if self._status == STATUS_NEEDS_PAIRING:
            raise NeedsPairing(self._error or "Not paired with this TV yet")
        if not self._remote or self._status != STATUS_CONNECTED:
            raise NotConnected(f"Not connected to the TV (status: {self._status})")
        return self._remote

    def send_key(self, key: int | str, direction: str = "SHORT") -> None:
        remote = self._require_remote()
        try:
            remote.send_key_command(resolve_key(key), resolve_direction(direction))
        except ConnectionClosed as exc:
            raise NotConnected(str(exc)) from exc

    def send_text(self, text: str) -> None:
        remote = self._require_remote()
        try:
            remote.send_text(text)
        except ConnectionClosed as exc:
            raise NotConnected(str(exc)) from exc

    def launch_app(self, app: str) -> None:
        """Launch by package ID (``com.netflix.ninja``) or deep link (``https://...``)."""
        remote = self._require_remote()
        try:
            remote.send_launch_app_command(app.strip())
        except ConnectionClosed as exc:
            raise NotConnected(str(exc)) from exc

    async def wake(self) -> bool:
        """Send Wake-on-LAN if we learned the TV's MAC during pairing."""
        if not self.mac:
            return False
        await asyncio.get_running_loop().run_in_executor(None, send_magic_packet, self.mac, self.host)
        return True

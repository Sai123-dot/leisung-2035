"""Local web server: a phone-friendly remote UI plus a small JSON/WebSocket API."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import socket
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from . import discovery
from .apps import COMMON_APPS
from .keys import UnknownKey, all_keycodes, list_aliases
from .tv import NeedsPairing, NotConnected, PairingFailed, TVController, TVError, TVUnreachable

LOGGER = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"

TV_KEY: web.AppKey[TVController] = web.AppKey("tv", object)  # type: ignore[type-var]
TOKEN_KEY: web.AppKey[str | None] = web.AppKey("token", object)  # type: ignore[type-var]
SOCKETS_KEY: web.AppKey[set[web.WebSocketResponse]] = web.AppKey("sockets", set)
LISTENER_KEY: web.AppKey[Any] = web.AppKey("listener", object)

ERROR_CODES: list[tuple[type[Exception], int, str]] = [
    (UnknownKey, 400, "unknown_key"),
    (ValueError, 400, "bad_request"),
    (KeyError, 400, "bad_request"),
    (NeedsPairing, 409, "needs_pairing"),
    (NotConnected, 503, "not_connected"),
    (TVUnreachable, 502, "unreachable"),
    (PairingFailed, 400, "pairing_failed"),
    (TVError, 500, "tv_error"),
]


def _classify(exc: Exception) -> tuple[int, str]:
    for cls, status, code in ERROR_CODES:
        if isinstance(exc, cls):
            return status, code
    return 500, "internal_error"


def _error(status: int, code: str, message: str, **extra: Any) -> web.Response:
    return web.json_response({"ok": False, "error": code, "message": message, **extra}, status=status)


def _ok(**payload: Any) -> web.Response:
    return web.json_response({"ok": True, **payload})


@web.middleware
async def auth_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    token = request.app[TOKEN_KEY]
    if token and (request.path.startswith("/api/") or request.path == "/ws"):
        supplied = request.headers.get("X-Auth-Token") or request.query.get("token") or ""
        if not secrets.compare_digest(supplied, token):
            return _error(401, "unauthorized", "Missing or invalid access token")
    return await handler(request)


@web.middleware
async def error_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - turned into a JSON error below
        status, code = _classify(exc)
        if status >= 500 and code == "internal_error":
            LOGGER.exception("Unhandled error in %s %s", request.method, request.path)
        return _error(status, code, str(exc) or code, state=request.app[TV_KEY].snapshot())


async def _json_body(request: web.Request) -> dict[str, Any]:
    if not request.can_read_body:
        return {}
    try:
        data = await request.json()
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")
    return data


def _require(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' is required")
    return value.strip()


# ---- handlers ----------------------------------------------------------------


async def index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def get_state(request: web.Request) -> web.Response:
    return _ok(state=request.app[TV_KEY].snapshot())


async def post_key(request: web.Request) -> web.Response:
    tv = request.app[TV_KEY]
    data = await _json_body(request)
    direction = str(data.get("direction") or "SHORT")
    keys: list[Any]
    if "keys" in data:
        if not isinstance(data["keys"], list) or not data["keys"]:
            raise ValueError("'keys' must be a non-empty list")
        keys = data["keys"]
    else:
        keys = [data.get("key")]
    delay = float(data.get("delay", 0.2))
    for index_, key in enumerate(keys):
        if key in (None, ""):
            raise ValueError("'key' is required")
        if index_:
            await asyncio.sleep(delay)
        tv.send_key(key, direction)
    return _ok(sent=keys, direction=direction.upper())


async def post_text(request: web.Request) -> web.Response:
    data = await _json_body(request)
    text = data.get("text")
    if not isinstance(text, str) or text == "":
        raise ValueError("'text' is required")
    request.app[TV_KEY].send_text(text)
    return _ok(sent=text)


async def post_app(request: web.Request) -> web.Response:
    data = await _json_body(request)
    app = _require(data, "app")
    request.app[TV_KEY].launch_app(app)
    return _ok(launched=app)


async def post_wake(request: web.Request) -> web.Response:
    tv = request.app[TV_KEY]
    sent = await tv.wake()
    if not sent:
        return _error(409, "no_mac", "The TV's MAC address is unknown; pair once while it is on.", state=tv.snapshot())
    return _ok(state=tv.snapshot())


async def post_connect(request: web.Request) -> web.Response:
    tv = request.app[TV_KEY]
    data = await _json_body(request)
    host = _require(data, "host")
    try:
        state = await tv.connect(host)
    except NeedsPairing:
        state = tv.snapshot()
    except TVUnreachable as exc:
        return _error(502, "unreachable", str(exc), state=tv.snapshot())
    return _ok(state=state)


async def post_pair_start(request: web.Request) -> web.Response:
    tv = request.app[TV_KEY]
    data = await _json_body(request)
    host = data.get("host")
    state = await tv.start_pairing(host.strip() if isinstance(host, str) and host.strip() else None)
    return _ok(state=state)


async def post_pair_finish(request: web.Request) -> web.Response:
    tv = request.app[TV_KEY]
    data = await _json_body(request)
    code = _require(data, "code")
    state = await tv.finish_pairing(code)
    return _ok(state=state)


async def get_discover(request: web.Request) -> web.Response:
    try:
        timeout = float(request.query.get("timeout", 4))
    except ValueError as exc:
        raise ValueError("'timeout' must be a number") from exc
    timeout = max(1.0, min(timeout, 15.0))
    tvs = await discovery.discover(timeout)
    return _ok(tvs=[tv.to_dict() for tv in tvs])


async def get_apps(request: web.Request) -> web.Response:
    return _ok(apps=COMMON_APPS)


async def get_keys(request: web.Request) -> web.Response:
    return _ok(keycodes=all_keycodes(), aliases=list_aliases())


async def websocket(request: web.Request) -> web.WebSocketResponse:
    tv = request.app[TV_KEY]
    sockets = request.app[SOCKETS_KEY]
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    sockets.add(ws)
    try:
        await ws.send_json({"type": "state", "state": tv.snapshot()})
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "error": "bad_request", "message": "Invalid JSON"})
                    continue
                if not isinstance(data, dict):
                    await ws.send_json({"type": "error", "error": "bad_request", "message": "Expected an object"})
                    continue
                await _handle_ws_message(ws, tv, data)
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSING):
                break
    finally:
        sockets.discard(ws)
    return ws


async def _handle_ws_message(ws: web.WebSocketResponse, tv: TVController, data: dict[str, Any]) -> None:
    kind = data.get("type")
    rid = data.get("id")
    try:
        if kind == "key":
            tv.send_key(data["key"], str(data.get("direction") or "SHORT"))
        elif kind == "text":
            tv.send_text(str(data["text"]))
        elif kind == "app":
            tv.launch_app(str(data["app"]))
        elif kind == "wake":
            await tv.wake()
        elif kind in ("state", "ping"):
            pass
        else:
            raise ValueError(f"Unknown message type {kind!r}")
    except Exception as exc:  # noqa: BLE001 - reported to the client
        _status, code = _classify(exc)
        if code == "internal_error":
            LOGGER.exception("Unhandled error in websocket message %r", kind)
        await ws.send_json({"type": "error", "id": rid, "error": code, "message": str(exc) or code})
        return
    await ws.send_json({"type": "pong" if kind == "ping" else "ack", "id": rid, "state": tv.snapshot()})


# ---- app factory ---------------------------------------------------------------


async def _broadcast(app: web.Application, state: dict[str, Any]) -> None:
    payload = json.dumps({"type": "state", "state": state})
    for ws in list(app[SOCKETS_KEY]):
        try:
            await ws.send_str(payload)
        except Exception:  # noqa: BLE001 - a dead socket is simply dropped
            app[SOCKETS_KEY].discard(ws)


async def _on_shutdown(app: web.Application) -> None:
    tv = app[TV_KEY]
    tv.remove_listener(app[LISTENER_KEY])
    for ws in list(app[SOCKETS_KEY]):
        await ws.close(code=1001, message=b"server shutdown")
    await tv.disconnect()


def create_app(tv: TVController, *, token: str | None = None) -> web.Application:
    """Build the aiohttp application around ``tv``."""
    app = web.Application(middlewares=[auth_middleware, error_middleware])
    app[TV_KEY] = tv
    app[TOKEN_KEY] = token or None
    app[SOCKETS_KEY] = set()

    app.router.add_get("/", index)
    app.router.add_get("/api/state", get_state)
    app.router.add_post("/api/key", post_key)
    app.router.add_post("/api/text", post_text)
    app.router.add_post("/api/app", post_app)
    app.router.add_post("/api/wake", post_wake)
    app.router.add_post("/api/connect", post_connect)
    app.router.add_post("/api/pair/start", post_pair_start)
    app.router.add_post("/api/pair/finish", post_pair_finish)
    app.router.add_get("/api/discover", get_discover)
    app.router.add_get("/api/apps", get_apps)
    app.router.add_get("/api/keys", get_keys)
    app.router.add_get("/ws", websocket)
    app.router.add_static("/static/", STATIC_DIR, name="static")

    def on_state(state: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_broadcast(app, state))

    app[LISTENER_KEY] = on_state
    tv.add_listener(on_state)
    app.on_shutdown.append(_on_shutdown)
    return app


def lan_ip() -> str | None:
    """Best guess of this machine's LAN address, for printing the phone URL."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return str(sock.getsockname()[0])
    except OSError:
        return None


def run(
    tv: TVController,
    *,
    bind: str = "0.0.0.0",
    port: int = 8765,
    token: str | None = None,
    autoconnect: bool = True,
) -> None:
    """Serve the remote UI until interrupted."""
    app = create_app(tv, token=token)

    async def startup(_app: web.Application) -> None:
        if autoconnect and tv.host:
            tv.start_background_connect()

    app.on_startup.append(startup)

    urls = [f"http://{bind}:{port}/"] if bind not in ("0.0.0.0", "::", "") else [f"http://localhost:{port}/"]
    ip = lan_ip() if bind in ("0.0.0.0", "::", "") else None
    if ip:
        urls.append(f"http://{ip}:{port}/")
    print("Hisense remote is running. Open one of these on a phone or computer on the same network:")
    for url in urls:
        print(f"  {url}")
    if token:
        print("  (an access token is required; enter it in the settings panel)")
    print(f"TV: {tv.host or 'not configured yet - use the settings panel to discover and pair'}")
    print("Press Ctrl+C to stop.")
    web.run_app(app, host=bind, port=port, print=None, access_log=None)

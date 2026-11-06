"""Command line interface: discover, pair, send, status, wake, serve."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any

from . import __version__
from .apps import COMMON_APPS
from .config import DEFAULT_CLIENT_NAME, ConfigStore
from .keys import all_keycodes, list_aliases
from .tv import HisenseTV, NeedsPairing, TVController, TVError

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hisense-remote",
        description="Control a Hisense Android TV / Google TV on your local network.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config-dir", help="where to keep the client certificate and known TVs")
    parser.add_argument(
        "--client-name",
        default=DEFAULT_CLIENT_NAME,
        help="name shown on the TV during pairing (default: %(default)s)",
    )
    parser.add_argument(
        "--no-ime",
        action="store_true",
        help="disable the on-TV keyboard channel (fixes a 'use keyboard on mobile' popup on some sets; "
        "the current app will then not be reported)",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0, help="-v for info, -vv for debug")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="find Android TVs on the network via mDNS")
    p.add_argument("--timeout", type=float, default=5.0, help="seconds to listen (default: %(default)s)")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = sub.add_parser("pair", help="pair with a TV (one-time; shows a code on the TV)")
    p.add_argument("host", nargs="?", help="TV IP address or hostname (omit to pick from discovery)")

    p = sub.add_parser("send", help="send one or more key presses")
    p.add_argument("keys", nargs="+", help="e.g. up down ok back home vol+ mute hdmi1 KEYCODE_POWER text:hello")
    p.add_argument("--host", help="TV address (default: last paired TV)")
    p.add_argument("--direction", default="SHORT", choices=["SHORT", "START_LONG", "END_LONG"])
    p.add_argument("--delay", type=float, default=0.25, help="seconds between keys (default: %(default)s)")

    p = sub.add_parser("text", help="type text on the TV (into the focused field)")
    p.add_argument("text")
    p.add_argument("--host")

    p = sub.add_parser("app", help="launch an app by package ID or deep link")
    p.add_argument("app", help="e.g. com.netflix.ninja, netflix, https://www.youtube.com/watch?v=...")
    p.add_argument("--host")

    p = sub.add_parser("status", help="show power state, current app, volume and device info")
    p.add_argument("--host")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("wake", help="send a Wake-on-LAN packet to the TV")
    p.add_argument("--host")
    p.add_argument("--mac", help="override the MAC learned during pairing")

    p = sub.add_parser("serve", help="run the web remote (open it on your phone)")
    p.add_argument("--host", help="TV address (default: last paired TV)")
    p.add_argument("--bind", default="0.0.0.0", help="interface to listen on (default: all)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--token", help="require this token for API access (optional)")
    p.add_argument("--demo", action="store_true", help="run against a simulated TV to try the UI")

    sub.add_parser("keys", help="list key names and aliases")
    sub.add_parser("apps", help="list known app package IDs")
    sub.add_parser("forget", help="forget the default TV (keeps the certificate)").add_argument("host", nargs="?")
    return parser


def _configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _make_tv(args: argparse.Namespace, host: str | None = None) -> HisenseTV:
    store = ConfigStore(args.config_dir)
    return HisenseTV(store, host, client_name=args.client_name, enable_ime=not args.no_ime)


def _app_id(value: str) -> str:
    for app in COMMON_APPS:
        if app["name"].lower() == value.lower():
            return app["id"]
    return value


async def _ainput(prompt: str) -> str:
    """``input()`` that does not block the event loop (the pairing socket must stay alive)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, input, prompt)


def _print_state(state: dict[str, Any]) -> None:
    power = {True: "on", False: "standby", None: "unknown"}[state.get("is_on")]
    print(f"TV:       {state.get('name') or '-'} ({state.get('host')})")
    print(f"Status:   {state.get('status')}" + (f" - {state['error']}" if state.get("error") else ""))
    print(f"Power:    {power}")
    app = state.get("current_app")
    if app:
        friendly = state.get("current_app_name")
        print(f"App:      {friendly + ' (' + app + ')' if friendly else app}")
    vol = state.get("volume")
    if vol:
        print(f"Volume:   {vol['level']}/{vol['max']}{' (muted)' if vol.get('muted') else ''}")
    dev = state.get("device")
    if dev:
        print(f"Device:   {dev.get('manufacturer', '')} {dev.get('model', '')} (software {dev.get('sw_version', '?')})")
    if state.get("mac"):
        print(f"MAC:      {state['mac']}")


# ---- commands ------------------------------------------------------------------


async def cmd_discover(args: argparse.Namespace) -> int:
    from . import discovery

    print(f"Listening for TVs for {args.timeout:g} s...", file=sys.stderr)
    tvs = await discovery.discover(args.timeout)
    if args.json:
        print(json.dumps([tv.to_dict() for tv in tvs], indent=2))
        return 0
    if not tvs:
        print("No TVs found. Make sure the TV is on, on the same Wi-Fi/LAN, and that your router allows mDNS.")
        print("You can still pair by IP: find it under Settings > Network & Internet on the TV, then run")
        print("  hisense-remote pair <ip>")
        return 1
    for tv in tvs:
        flag = "remote ready" if tv.remote_service else "cast only (remote service off?)"
        model = f" - {tv.model}" if tv.model else ""
        print(f"{tv.host:<16} {tv.name}{model} [{flag}]")
    return 0


async def _pick_host(args: argparse.Namespace) -> str | None:
    from . import discovery

    print("Looking for TVs on the network (5 s)...")
    tvs = [tv for tv in await discovery.discover(5.0)]
    if not tvs:
        print("Nothing found via mDNS. Enter the TV's IP address instead (Settings > Network & Internet on the TV).")
        answer = (await _ainput("TV IP address: ")).strip()
        return answer or None
    for i, tv in enumerate(tvs, 1):
        flag = "" if tv.remote_service else "  (remote service not advertised)"
        print(f"  {i}. {tv.name} - {tv.host}{flag}")
    answer = (await _ainput("Pick a TV number, or type an IP address: ")).strip()
    if answer.isdigit() and 1 <= int(answer) <= len(tvs):
        return tvs[int(answer) - 1].host
    return answer or None


async def cmd_pair(args: argparse.Namespace) -> int:
    host = args.host or await _pick_host(args)
    if not host:
        print("No TV selected.")
        return 1
    tv = _make_tv(args, host)
    print(f"Pairing with {host}: a code will appear on the TV screen.")
    try:
        await tv.start_pairing(host)
        name = f" ({tv.name})" if tv.name else ""
        code = (await _ainput(f"Enter the 6-character code shown on the TV{name}: ")).strip()
        state = await tv.finish_pairing(code)
    except TVError as exc:
        print(f"Pairing failed: {exc}")
        await tv.disconnect()
        return 1
    print(f"Paired with {state.get('name') or host}. It is now the default TV.")
    await asyncio.sleep(0.5)
    await tv.disconnect()
    return 0


async def _connected_tv(args: argparse.Namespace) -> HisenseTV:
    tv = _make_tv(args, getattr(args, "host", None))
    if not tv.host:
        raise TVError("No TV configured yet. Run 'hisense-remote pair' first or pass --host.")
    try:
        await tv.connect()
    except NeedsPairing as exc:
        raise TVError(f"{exc}. Run: hisense-remote pair {tv.host}") from exc
    return tv


async def cmd_send(args: argparse.Namespace) -> int:
    tv = await _connected_tv(args)
    try:
        for i, key in enumerate(args.keys):
            if i:
                await asyncio.sleep(args.delay)
            tv.send_key(key, args.direction)
        await asyncio.sleep(0.3)  # let the transport flush before closing
    finally:
        await tv.disconnect()
    print(f"Sent: {' '.join(args.keys)}")
    return 0


async def cmd_text(args: argparse.Namespace) -> int:
    tv = await _connected_tv(args)
    try:
        tv.send_text(args.text)
        await asyncio.sleep(0.3)
    finally:
        await tv.disconnect()
    print("Sent.")
    return 0


async def cmd_app(args: argparse.Namespace) -> int:
    tv = await _connected_tv(args)
    app = _app_id(args.app)
    try:
        tv.launch_app(app)
        await asyncio.sleep(0.3)
    finally:
        await tv.disconnect()
    print(f"Launched {app}.")
    return 0


async def cmd_status(args: argparse.Namespace) -> int:
    tv = await _connected_tv(args)
    try:
        await asyncio.sleep(1.0)  # the TV pushes power/app/volume right after connecting
        state = tv.snapshot()
    finally:
        await tv.disconnect()
    if args.json:
        print(json.dumps(state, indent=2))
    else:
        _print_state(state)
    return 0


async def cmd_wake(args: argparse.Namespace) -> int:
    from .tv import send_magic_packet

    tv = _make_tv(args, args.host)
    mac = args.mac or tv.mac
    if not mac:
        print("No MAC address known for this TV. Pair once while it is on, or pass --mac.")
        return 1
    send_magic_packet(mac, tv.host)
    print(f"Wake-on-LAN sent to {mac}. The TV needs 'network standby' / 'wake on LAN' enabled to react.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from . import server

    tv: TVController
    if args.demo:
        from .fake import FakeTV

        tv = FakeTV()
        print("Demo mode: commands go to a simulated TV.")
    else:
        tv = _make_tv(args, args.host)
    server.run(tv, bind=args.bind, port=args.port, token=args.token)
    return 0


def cmd_keys(_args: argparse.Namespace) -> int:
    print("Aliases:")
    for alias, name in list_aliases().items():
        print(f"  {alias:<14} -> {name}")
    print("\nAll key codes (use with or without the KEYCODE_ prefix):")
    for name in all_keycodes():
        print(f"  {name}")
    return 0


def cmd_apps(_args: argparse.Namespace) -> int:
    for app in COMMON_APPS:
        print(f"  {app['name']:<14} {app['id']}")
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    store = ConfigStore(args.config_dir)
    host = args.host or store.default_host
    if not host:
        print("Nothing to forget.")
        return 0
    store.forget_tv(host)
    print(f"Forgot {host}.")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    handlers: dict[str, Any] = {
        "discover": cmd_discover,
        "pair": cmd_pair,
        "send": cmd_send,
        "text": cmd_text,
        "app": cmd_app,
        "status": cmd_status,
        "wake": cmd_wake,
        "serve": cmd_serve,
        "keys": cmd_keys,
        "apps": cmd_apps,
        "forget": cmd_forget,
    }
    handler = handlers[args.command]
    try:
        result = handler(args)
        code = asyncio.run(result) if asyncio.iscoroutine(result) else result
    except KeyboardInterrupt:
        code = 130
    except TVError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        code = 2
    except BrokenPipeError:  # e.g. `hisense-remote keys | head`
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            pass
        code = 0
    sys.exit(code)

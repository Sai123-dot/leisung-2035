"""Find Android TVs on the local network with mDNS (zeroconf)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from typing import Any

from zeroconf import IPVersion, ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

LOGGER = logging.getLogger(__name__)

# Advertised by the "Android TV Remote Service" that we pair with.
REMOTE_SERVICE = "_androidtvremote2._tcp.local."
# Advertised by Chromecast built-in; useful to spot a TV whose remote service is off.
CAST_SERVICE = "_googlecast._tcp.local."


@dataclass
class DiscoveredTV:
    host: str
    name: str
    port: int | None = None
    model: str | None = None
    remote_service: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decode_properties(props: dict[Any, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (props or {}).items():
        k = key.decode(errors="replace") if isinstance(key, bytes) else str(key)
        if isinstance(value, bytes):
            out[k] = value.decode(errors="replace")
        elif value is not None:
            out[k] = str(value)
    return out


async def discover(timeout: float = 5.0) -> list[DiscoveredTV]:
    """Browse for ``timeout`` seconds and return the TVs seen, remote-capable ones first."""
    found: dict[str, DiscoveredTV] = {}
    pending: set[asyncio.Task[None]] = set()
    try:
        aiozc = AsyncZeroconf()
    except OSError as exc:
        LOGGER.warning("mDNS discovery is not available on this machine: %s", exc)
        return []

    async def resolve(service_type: str, name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        if not await info.async_request(aiozc.zeroconf, 3000):
            return
        addresses = info.parsed_addresses(IPVersion.V4Only) or info.parsed_addresses()
        if not addresses:
            return
        host = addresses[0]
        props = _decode_properties(info.properties)
        entry = found.get(host) or DiscoveredTV(host=host, name=name.removesuffix("." + service_type))
        if service_type == REMOTE_SERVICE:
            entry.remote_service = True
            entry.port = info.port
            entry.name = name.removesuffix("." + service_type)
        else:
            entry.model = props.get("md") or entry.model
            if not entry.remote_service and props.get("fn"):
                entry.name = props["fn"]
        found[host] = entry

    def on_change(
        zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange
    ) -> None:
        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            task = asyncio.ensure_future(resolve(service_type, name))
            pending.add(task)
            task.add_done_callback(pending.discard)

    browser = AsyncServiceBrowser(aiozc.zeroconf, [REMOTE_SERVICE, CAST_SERVICE], handlers=[on_change])
    try:
        await asyncio.sleep(timeout)
        if pending:
            await asyncio.wait(pending, timeout=3)
    finally:
        await browser.async_cancel()
        await aiozc.async_close()

    return sorted(found.values(), key=lambda tv: (not tv.remote_service, tv.name.lower()))

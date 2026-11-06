"""Friendly key names mapped to the Android ``KEYCODE_*`` names the TV understands."""

from __future__ import annotations

from androidtvremote2 import remotemessage_pb2 as _pb

KEYCODE_PREFIX = "KEYCODE_"
TEXT_PREFIX = "text:"
DIRECTIONS = ("SHORT", "START_LONG", "END_LONG")


class UnknownKey(ValueError):
    """Raised for a key name the TV does not know."""


# Short names people actually type, mapped to the suffix after KEYCODE_.
ALIASES: dict[str, str] = {
    # power
    "power": "POWER",
    "wake": "WAKEUP",
    "wakeup": "WAKEUP",
    "sleep": "SLEEP",
    "standby": "SLEEP",
    # navigation
    "up": "DPAD_UP",
    "down": "DPAD_DOWN",
    "left": "DPAD_LEFT",
    "right": "DPAD_RIGHT",
    "ok": "DPAD_CENTER",
    "select": "DPAD_CENTER",
    "center": "DPAD_CENTER",
    "enter": "ENTER",
    "back": "BACK",
    "home": "HOME",
    "menu": "MENU",
    "recent": "APP_SWITCH",
    "recents": "APP_SWITCH",
    "apps": "APP_SWITCH",
    "settings": "SETTINGS",
    "search": "SEARCH",
    "assist": "ASSIST",
    "voice": "VOICE_ASSIST",
    "info": "INFO",
    "guide": "GUIDE",
    "captions": "CAPTIONS",
    "subtitles": "CAPTIONS",
    "cc": "CAPTIONS",
    "bookmark": "BOOKMARK",
    # volume
    "vol+": "VOLUME_UP",
    "volup": "VOLUME_UP",
    "volumeup": "VOLUME_UP",
    "volume_up": "VOLUME_UP",
    "vol-": "VOLUME_DOWN",
    "voldown": "VOLUME_DOWN",
    "volumedown": "VOLUME_DOWN",
    "volume_down": "VOLUME_DOWN",
    "mute": "VOLUME_MUTE",
    "unmute": "VOLUME_MUTE",
    # channels
    "ch+": "CHANNEL_UP",
    "chup": "CHANNEL_UP",
    "channel_up": "CHANNEL_UP",
    "ch-": "CHANNEL_DOWN",
    "chdown": "CHANNEL_DOWN",
    "channel_down": "CHANNEL_DOWN",
    "last": "LAST_CHANNEL",
    "tv": "TV",
    # media
    "play": "MEDIA_PLAY",
    "pause": "MEDIA_PAUSE",
    "playpause": "MEDIA_PLAY_PAUSE",
    "play_pause": "MEDIA_PLAY_PAUSE",
    "stop": "MEDIA_STOP",
    "next": "MEDIA_NEXT",
    "prev": "MEDIA_PREVIOUS",
    "previous": "MEDIA_PREVIOUS",
    "rew": "MEDIA_REWIND",
    "rewind": "MEDIA_REWIND",
    "ff": "MEDIA_FAST_FORWARD",
    "fastforward": "MEDIA_FAST_FORWARD",
    "forward": "MEDIA_FAST_FORWARD",
    "record": "MEDIA_RECORD",
    "audio": "MEDIA_AUDIO_TRACK",
    # inputs
    "input": "TV_INPUT",
    "source": "TV_INPUT",
    "hdmi1": "TV_INPUT_HDMI_1",
    "hdmi2": "TV_INPUT_HDMI_2",
    "hdmi3": "TV_INPUT_HDMI_3",
    "hdmi4": "TV_INPUT_HDMI_4",
    # colour buttons
    "red": "PROG_RED",
    "green": "PROG_GREEN",
    "yellow": "PROG_YELLOW",
    "blue": "PROG_BLUE",
    # text editing
    "delete": "DEL",
    "backspace": "DEL",
    "space": "SPACE",
    "tab": "TAB",
    "escape": "ESCAPE",
    "esc": "ESCAPE",
}


def resolve_key(key: int | str) -> int | str:
    """Turn an alias, bare name or ``KEYCODE_*`` name into a validated key code.

    ``text:...`` values are passed through untouched so they reach ``send_text``.
    Integers are validated against the protocol enum and returned as-is.
    """
    if isinstance(key, bool):
        raise UnknownKey(f"Unknown key {key!r}")
    if isinstance(key, int):
        try:
            _pb.RemoteKeyCode.Name(key)
        except ValueError as exc:
            raise UnknownKey(f"Unknown key code {key}") from exc
        return key
    if not isinstance(key, str):
        raise UnknownKey(f"Unknown key {key!r}")

    raw = key.strip()
    if raw.lower().startswith(TEXT_PREFIX):
        return raw
    name = ALIASES.get(raw.lower())
    if name is None:
        name = raw.upper().replace("-", "_").replace(" ", "_")
        if name.startswith(KEYCODE_PREFIX):
            name = name[len(KEYCODE_PREFIX) :]
    full = KEYCODE_PREFIX + name
    try:
        _pb.RemoteKeyCode.Value(full)
    except ValueError as exc:
        raise UnknownKey(f"Unknown key {key!r}") from exc
    return full


def resolve_direction(direction: str | None) -> str:
    """Validate a press direction: SHORT (tap), START_LONG (hold) or END_LONG (release)."""
    value = (direction or "SHORT").strip().upper()
    if value not in DIRECTIONS:
        raise ValueError(f"Unknown direction {direction!r}; expected one of {', '.join(DIRECTIONS)}")
    return value


def all_keycodes() -> list[str]:
    """Every ``KEYCODE_*`` name the protocol defines."""
    return sorted(name for name in _pb.RemoteKeyCode.keys() if name != "KEYCODE_UNKNOWN")


def list_aliases() -> dict[str, str]:
    """Alias -> full ``KEYCODE_*`` name."""
    return {alias: KEYCODE_PREFIX + name for alias, name in ALIASES.items()}

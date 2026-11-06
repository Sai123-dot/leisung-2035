"""Package IDs of apps commonly installed on Hisense Android/Google TV sets."""

from __future__ import annotations

COMMON_APPS: list[dict[str, str]] = [
    {"name": "Netflix", "id": "com.netflix.ninja", "color": "#E50914"},
    {"name": "YouTube", "id": "com.google.android.youtube.tv", "color": "#FF0000"},
    {"name": "Prime Video", "id": "com.amazon.amazonvideo.livingroom", "color": "#00A8E1"},
    {"name": "Disney+", "id": "com.disney.disneyplus", "color": "#113CCF"},
    {"name": "Spotify", "id": "com.spotify.tv.android", "color": "#1DB954"},
    {"name": "Plex", "id": "com.plexapp.android", "color": "#E5A00D"},
    {"name": "Apple TV", "id": "com.apple.atve.androidtv.appletv", "color": "#A2AAAD"},
    {"name": "Max", "id": "com.wbd.stream", "color": "#002BE7"},
    {"name": "Hulu", "id": "com.hulu.livingroomplus", "color": "#1CE783"},
    {"name": "Twitch", "id": "tv.twitch.android.app", "color": "#9146FF"},
    {"name": "YouTube Music", "id": "com.google.android.youtube.tvmusic", "color": "#FF0000"},
    {"name": "Jellyfin", "id": "org.jellyfin.androidtv", "color": "#00A4DC"},
    {"name": "Kodi", "id": "org.xbmc.kodi", "color": "#17B2E7"},
    {"name": "VLC", "id": "org.videolan.vlc", "color": "#FF8800"},
    {"name": "Play Store", "id": "com.android.vending", "color": "#01875F"},
    {"name": "Settings", "id": "com.android.tv.settings", "color": "#8E8E93"},
]


def app_name(package: str | None) -> str | None:
    """Friendly name for a package ID when we know it."""
    if not package:
        return None
    for app in COMMON_APPS:
        if app["id"] == package:
            return app["name"]
    return None

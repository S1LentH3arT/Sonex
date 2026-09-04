"""Cover sources support for tool implementations used by the planner and playback flows.

Implements the cover_sources module responsibilities used by Sonex runtime flows.
Key public entry points include cover_bytes_for_source, register_cover_bytes, extract_embedded_cover, resolve_online_cover, lookup_cover_art_url.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.tools.cover_source_state import (
    caa_front_endpoints as _caa_front_endpoints,
    provider_cover_url as _provider_cover_url,
    recording_cover_ids as _recording_cover_ids,
    score_recording as _score_recording,
    terms as _terms,
)

MUSICBRAINZ_USER_AGENT = "Sonex/1.0 (https://github.com/sonex)"
MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/recording"
COVER_ART_ARCHIVE_BASE = "https://coverartarchive.org"
MUSICBRAINZ_MIN_INTERVAL_SECONDS = 1.0

_embedded_cover_bytes: dict[str, bytes] = {}
_musicbrainz_lock = threading.Lock()
_last_musicbrainz_request = 0.0


def cover_bytes_for_source(source: str) -> bytes | None:
    """Coordinates cover bytes for source for the current Sonex flow.

    Typical use: Use this function when runtime code needs cover bytes for source as part of a Sonex command, playback, auth, llm, or ui path.

    Example: cover_bytes_for_source(source=...) -> returns the value used by the surrounding Sonex flow.
    """
    return _embedded_cover_bytes.get(source)


def register_cover_bytes(image_bytes: bytes) -> str:
    """Coordinates register cover bytes for the current Sonex flow.

    Typical use: Use this function when runtime code needs register cover bytes as part of a Sonex command, playback, auth, llm, or ui path.

    Example: register_cover_bytes(image_bytes=...) -> returns the value used by the surrounding Sonex flow.
    """
    digest = hashlib.sha256(image_bytes).hexdigest()
    source = f"embedded:{digest}"
    _embedded_cover_bytes[source] = image_bytes
    return source


def extract_embedded_cover(path: str | Path) -> dict[str, Any] | None:
    """Coordinates extract embedded cover for the current Sonex flow.

    Typical use: Use this function when runtime code needs extract embedded cover as part of a Sonex command, playback, auth, llm, or ui path.

    Example: extract_embedded_cover(path=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        from mutagen import File
        from mutagen.flac import Picture
        from mutagen.id3 import APIC, ID3
        from mutagen.mp4 import MP4Cover
    except ImportError as exc:
        raise RuntimeError("mutagen is required to read embedded cover art.") from exc

    def id3_fallback() -> dict[str, Any] | None:
        """Coordinates id3 fallback for the current Sonex flow.

        Typical use: Use this function when runtime code needs id3 fallback as part of a Sonex command, playback, auth, llm, or ui path.

        Example: id3_fallback() -> returns the value used by the surrounding Sonex flow.
        """
        try:
            tags = ID3(str(path))
        except Exception:
            return None
        for value in tags.values():
            if isinstance(value, APIC) and value.data:
                source = register_cover_bytes(bytes(value.data))
                return {
                    "cover_source": source,
                    "cover_bytes": bytes(value.data),
                    "mime_type": value.mime,
                    "source_type": "embedded",
                }
        return None

    try:
        audio = File(str(path))
    except Exception:
        return id3_fallback()
    if audio is None:
        return id3_fallback()

    image_bytes: bytes | None = None
    mime_type: str | None = None

    try:
        pictures = getattr(audio, "pictures", None)
        if pictures:
            front = next((pic for pic in pictures if getattr(pic, "type", None) == 3), pictures[0])
            if isinstance(front, Picture):
                image_bytes = bytes(front.data)
                mime_type = front.mime
    except Exception:
        image_bytes = None

    if image_bytes is None:
        tags = getattr(audio, "tags", None)
        values = list(tags.values()) if tags is not None and hasattr(tags, "values") else []
        for value in values:
            if isinstance(value, APIC):
                image_bytes = bytes(value.data)
                mime_type = value.mime
                break
        if image_bytes is None:
            covr = tags.get("covr") if tags is not None and hasattr(tags, "get") else None
            if isinstance(covr, list) and covr:
                cover = covr[0]
                if isinstance(cover, (bytes, MP4Cover)):
                    image_bytes = bytes(cover)
                    image_format = getattr(cover, "imageformat", None)
                    mime_type = "image/png" if image_format == MP4Cover.FORMAT_PNG else "image/jpeg"

    if not image_bytes:
        return None

    source = register_cover_bytes(image_bytes)
    return {
        "cover_source": source,
        "cover_bytes": image_bytes,
        "mime_type": mime_type,
        "source_type": "embedded",
    }


def resolve_online_cover(metadata: dict[str, Any]) -> dict[str, Any]:
    """Resolves online cover from available runtime state.

    Typical use: Use this function when runtime code needs resolve online cover as part of a Sonex command, playback, auth, llm, or ui path.

    Example: resolve_online_cover(metadata=...) -> returns the value used by the surrounding Sonex flow.
    """
    provider_cover = _provider_cover_url(metadata)
    if provider_cover:
        return {
            "cover_source": provider_cover,
            "cover_url": provider_cover,
            "source_type": "provider",
        }

    caa_url = lookup_cover_art_url(
        name=str(metadata.get("name") or metadata.get("title") or "").strip(),
        artist=str(metadata.get("artist") or "").strip(),
        album=str(metadata.get("album") or "").strip(),
    )
    if caa_url:
        return {
            "cover_source": caa_url,
            "cover_url": caa_url,
            "source_type": "cover_art_archive",
        }
    return {}


def lookup_cover_art_url(*, name: str, artist: str, album: str = "") -> str | None:
    """Coordinates lookup cover art url for the current Sonex flow.

    Typical use: Use this function when runtime code needs lookup cover art url as part of a Sonex command, playback, auth, llm, or ui path.

    Example: lookup_cover_art_url(name=..., artist=..., album=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not name or not artist:
        return None
    try:
        release_group_mbid, release_mbid = _musicbrainz_cover_candidates(name=name, artist=artist, album=album)
    except Exception:
        return None

    for endpoint in _caa_front_endpoints(release_group_mbid, release_mbid):
        if _cover_art_exists(endpoint):
            return endpoint
    return None


def _musicbrainz_cover_candidates(*, name: str, artist: str, album: str) -> tuple[str | None, str | None]:
    """Prepares musicbrainz cover candidates for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs musicbrainz cover candidates without duplicating the local rules.

    Example: _musicbrainz_cover_candidates(name=..., artist=..., album=...) -> returns the value used by the surrounding Sonex flow.
    """
    query_parts = [f'recording:"{name}"', f'artist:"{artist}"']
    if album and album != "-":
        query_parts.append(f'release:"{album}"')
    params = urlencode({"query": " AND ".join(query_parts), "fmt": "json", "limit": "5"})
    payload = _musicbrainz_json(f"{MUSICBRAINZ_SEARCH_URL}?{params}")
    recordings = payload.get("recordings") if isinstance(payload, dict) else None
    if not isinstance(recordings, list):
        return None, None

    best_score = -1
    best_release_group: str | None = None
    best_release: str | None = None
    name_terms = _terms(name)
    artist_terms = _terms(artist)
    album_terms = _terms(album)
    for recording in recordings:
        if not isinstance(recording, dict):
            continue
        score = _score_recording(recording, name_terms=name_terms, artist_terms=artist_terms, album_terms=album_terms)
        if score < 4 or score <= best_score:
            continue
        release_group, release = _recording_cover_ids(recording)
        if release_group or release:
            best_score = score
            best_release_group = release_group
            best_release = release
    return best_release_group, best_release


def _musicbrainz_json(url: str) -> dict[str, Any]:
    """Prepares musicbrainz json for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs musicbrainz json without duplicating the local rules.

    Example: _musicbrainz_json(url=...) -> returns the value used by the surrounding Sonex flow.
    """
    global _last_musicbrainz_request
    with _musicbrainz_lock:
        elapsed = time.monotonic() - _last_musicbrainz_request
        if elapsed < MUSICBRAINZ_MIN_INTERVAL_SECONDS:
            time.sleep(MUSICBRAINZ_MIN_INTERVAL_SECONDS - elapsed)
        _last_musicbrainz_request = time.monotonic()

    request = Request(url, headers={"User-Agent": MUSICBRAINZ_USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=6) as response:
        return json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))


def _cover_art_exists(url: str) -> bool:
    """Prepares cover art exists for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs cover art exists without duplicating the local rules.

    Example: _cover_art_exists(url=...) -> returns the value used by the surrounding Sonex flow.
    """
    request = Request(url, headers={"User-Agent": MUSICBRAINZ_USER_AGENT})
    try:
        with urlopen(request, timeout=6):
            return True
    except Exception:
        return False

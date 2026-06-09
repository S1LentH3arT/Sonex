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
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

MUSICBRAINZ_USER_AGENT = "Sonex/1.0 (https://github.com/sonex)"
MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/recording"
COVER_ART_ARCHIVE_BASE = "https://coverartarchive.org"
MUSICBRAINZ_MIN_INTERVAL_SECONDS = 1.0

_embedded_cover_bytes: dict[str, bytes] = {}
_musicbrainz_lock = threading.Lock()
_last_musicbrainz_request = 0.0


def cover_bytes_for_source(source: str) -> bytes | None:
    """Cover bytes for source.

    Coordinates cover bytes for source logic for the surrounding Sonex flow.

    Args:
        source: Input value used by the cover bytes for source operation.

    Returns:
        The computed result for cover bytes for source.
    """
    return _embedded_cover_bytes.get(source)


def register_cover_bytes(image_bytes: bytes) -> str:
    """Register cover bytes.

    Coordinates register cover bytes logic for the surrounding Sonex flow.

    Args:
        image_bytes: Input value used by the register cover bytes operation.

    Returns:
        The computed result for register cover bytes.
    """
    digest = hashlib.sha256(image_bytes).hexdigest()
    source = f"embedded:{digest}"
    _embedded_cover_bytes[source] = image_bytes
    return source


def extract_embedded_cover(path: str | Path) -> dict[str, Any] | None:
    """Extract embedded cover.

    Coordinates extract embedded cover logic for the surrounding Sonex flow.

    Args:
        path: Input value used by the extract embedded cover operation.

    Returns:
        The computed result for extract embedded cover.
    """
    try:
        from mutagen import File
        from mutagen.flac import Picture
        from mutagen.id3 import APIC, ID3
        from mutagen.mp4 import MP4Cover
    except ImportError as exc:
        raise RuntimeError("mutagen is required to read embedded cover art.") from exc

    def id3_fallback() -> dict[str, Any] | None:
        """Id3 fallback.

        Coordinates id3 fallback logic for the surrounding Sonex flow.

        Returns:
            The computed result for id3 fallback.
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
    """Resolve online cover.

    Coordinates resolve online cover logic for the surrounding Sonex flow.

    Args:
        metadata: Input value used by the resolve online cover operation.

    Returns:
        The computed result for resolve online cover.
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


def _provider_cover_url(metadata: dict[str, Any]) -> str | None:
    """Provider cover url.

    Coordinates provider cover url logic for the surrounding Sonex flow.

    Args:
        metadata: Input value used by the provider cover url operation.

    Returns:
        The computed result for provider cover url.
    """
    explicit = _text(metadata.get("official_album_cover_url") or metadata.get("provider_album_cover_url"))
    if explicit:
        return explicit
    provider = str(metadata.get("provider") or "").lower()
    cover_url = _text(metadata.get("album_cover_url") or metadata.get("cover_url") or metadata.get("image_url"))
    if not cover_url:
        return None
    if provider == "youtube" or "ytimg.com/" in cover_url:
        return None
    return cover_url


def lookup_cover_art_url(*, name: str, artist: str, album: str = "") -> str | None:
    """Lookup cover art url.

    Coordinates lookup cover art url logic for the surrounding Sonex flow.

    Args:
        name: Input value used by the lookup cover art url operation.
        artist: Input value used by the lookup cover art url operation.
        album: Input value used by the lookup cover art url operation.

    Returns:
        The computed result for lookup cover art url.
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
    """Musicbrainz cover candidates.

    Coordinates musicbrainz cover candidates logic for the surrounding Sonex flow.

    Args:
        name: Input value used by the musicbrainz cover candidates operation.
        artist: Input value used by the musicbrainz cover candidates operation.
        album: Input value used by the musicbrainz cover candidates operation.

    Returns:
        The computed result for musicbrainz cover candidates.
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
    """Musicbrainz json.

    Coordinates musicbrainz json logic for the surrounding Sonex flow.

    Args:
        url: Input value used by the musicbrainz json operation.

    Returns:
        The computed result for musicbrainz json.
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


def _recording_cover_ids(recording: dict[str, Any]) -> tuple[str | None, str | None]:
    """Recording cover ids.

    Coordinates recording cover ids logic for the surrounding Sonex flow.

    Args:
        recording: Input value used by the recording cover ids operation.

    Returns:
        The computed result for recording cover ids.
    """
    releases = recording.get("releases")
    if not isinstance(releases, list):
        return None, None
    for release in releases:
        if not isinstance(release, dict):
            continue
        release_group = release.get("release-group") if isinstance(release.get("release-group"), dict) else {}
        release_group_id = _text(release_group.get("id"))
        release_id = _text(release.get("id"))
        if release_group_id or release_id:
            return release_group_id, release_id
    return None, None


def _score_recording(
    recording: dict[str, Any],
    *,
    name_terms: set[str],
    artist_terms: set[str],
    album_terms: set[str],
) -> int:
    """Score recording.

    Coordinates score recording logic for the surrounding Sonex flow.

    Args:
        recording: Input value used by the score recording operation.
        name_terms: Input value used by the score recording operation.
        artist_terms: Input value used by the score recording operation.
        album_terms: Input value used by the score recording operation.

    Returns:
        The computed result for score recording.
    """
    score = 0
    title_terms = _terms(str(recording.get("title") or ""))
    if name_terms and name_terms <= title_terms:
        score += 3
    artist_credit = " ".join(
        str(credit.get("name") or "")
        for credit in recording.get("artist-credit") or []
        if isinstance(credit, dict)
    )
    if artist_terms and artist_terms <= _terms(artist_credit):
        score += 3
    if album_terms:
        release_titles = {
            term
            for release in recording.get("releases") or []
            if isinstance(release, dict)
            for term in _terms(str(release.get("title") or ""))
        }
        if album_terms <= release_titles:
            score += 2
    try:
        score += min(2, max(0, int(recording.get("score") or 0) // 50))
    except (TypeError, ValueError):
        pass
    return score


def _caa_front_endpoints(release_group_mbid: str | None, release_mbid: str | None) -> list[str]:
    """Caa front endpoints.

    Coordinates caa front endpoints logic for the surrounding Sonex flow.

    Args:
        release_group_mbid: Input value used by the caa front endpoints operation.
        release_mbid: Input value used by the caa front endpoints operation.

    Returns:
        The computed result for caa front endpoints.
    """
    endpoints: list[str] = []
    if release_group_mbid:
        endpoints.append(f"{COVER_ART_ARCHIVE_BASE}/release-group/{quote(release_group_mbid)}/front-500")
    if release_mbid:
        endpoints.append(f"{COVER_ART_ARCHIVE_BASE}/release/{quote(release_mbid)}/front-500")
    return endpoints


def _cover_art_exists(url: str) -> bool:
    """Cover art exists.

    Coordinates cover art exists logic for the surrounding Sonex flow.

    Args:
        url: Input value used by the cover art exists operation.

    Returns:
        The computed result for cover art exists.
    """
    request = Request(url, headers={"User-Agent": MUSICBRAINZ_USER_AGENT})
    try:
        with urlopen(request, timeout=6):
            return True
    except Exception:
        return False


def _terms(value: str) -> set[str]:
    """Terms.

    Coordinates terms logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the terms operation.

    Returns:
        The computed result for terms.
    """
    return {part.casefold() for part in value.replace("-", " ").split() if part.strip() and part != "-"}


def _text(value: Any) -> str | None:
    """Text.

    Coordinates text logic for the surrounding Sonex flow.

    Args:
        value: Input value used by the text operation.

    Returns:
        The computed result for text.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None

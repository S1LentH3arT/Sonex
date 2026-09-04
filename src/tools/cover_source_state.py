"""Pure metadata policies for online cover lookup."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


def text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def provider_cover_url(metadata: dict[str, Any]) -> str | None:
    explicit = text(metadata.get("official_album_cover_url") or metadata.get("provider_album_cover_url"))
    if explicit:
        return explicit
    provider = str(metadata.get("provider") or "").lower()
    cover_url = text(metadata.get("album_cover_url") or metadata.get("cover_url") or metadata.get("image_url"))
    if not cover_url or provider == "youtube" or "ytimg.com/" in cover_url:
        return None
    return cover_url


def recording_cover_ids(recording: dict[str, Any]) -> tuple[str | None, str | None]:
    releases = recording.get("releases")
    if not isinstance(releases, list):
        return None, None
    for release in releases:
        if not isinstance(release, dict):
            continue
        group = release.get("release-group") if isinstance(release.get("release-group"), dict) else {}
        group_id = text(group.get("id"))
        release_id = text(release.get("id"))
        if group_id or release_id:
            return group_id, release_id
    return None, None


def terms(value: str) -> set[str]:
    return {part.casefold() for part in value.replace("-", " ").split() if part.strip() and part != "-"}


def score_recording(
    recording: dict[str, Any],
    *,
    name_terms: set[str],
    artist_terms: set[str],
    album_terms: set[str],
) -> int:
    score = 0
    if name_terms and name_terms <= terms(str(recording.get("title") or "")):
        score += 3
    artist_credit = " ".join(
        str(credit.get("name") or "")
        for credit in recording.get("artist-credit") or []
        if isinstance(credit, dict)
    )
    if artist_terms and artist_terms <= terms(artist_credit):
        score += 3
    if album_terms:
        release_titles = {
            term
            for release in recording.get("releases") or []
            if isinstance(release, dict)
            for term in terms(str(release.get("title") or ""))
        }
        if album_terms <= release_titles:
            score += 2
    try:
        score += min(2, max(0, int(recording.get("score") or 0) // 50))
    except (TypeError, ValueError):
        pass
    return score


def caa_front_endpoints(release_group_mbid: str | None, release_mbid: str | None) -> list[str]:
    endpoints: list[str] = []
    if release_group_mbid:
        base = f"https://coverartarchive.org/release-group/{quote(release_group_mbid)}"
        endpoints.extend([f"{base}/front", f"{base}/front-500"])
    if release_mbid:
        base = f"https://coverartarchive.org/release/{quote(release_mbid)}"
        endpoints.extend([f"{base}/front", f"{base}/front-500"])
    return endpoints

"""Track search support for tool implementations used by the planner and playback flows.

Implements the track_search module responsibilities used by Sonex runtime flows.
Key public entry points include search_track_metadata_candidates.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from threading import Lock
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.llm.transport import sanitize_error_message
from src.tools.cover_sources import (
    MUSICBRAINZ_MIN_INTERVAL_SECONDS,
    MUSICBRAINZ_SEARCH_URL,
    MUSICBRAINZ_USER_AGENT,
)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
DEEZER_SEARCH_URL = "https://api.deezer.com/search/track"
DEFAULT_ITUNES_COUNTRY = "US"
DEFAULT_ITUNES_COUNTRIES = ("US", "TW", "HK", "CN")
CJK_ITUNES_COUNTRIES = ("TW", "HK", "CN", "US")
TRADITIONAL_CHINESE_MARKERS = frozenset(
    "萬與專業東絲兩嚴喪個豐臨為麗舉麼義烏樂喬習鄉書買亂爭於虧雲亞產親億僅從倉儀們價眾優會傘偉傳傷倫偽體餘來偵側僑儉償兒兌黨蘭關興養獸內岡冊寫軍農凍淨幹幾庫應廠廢廣開異棄張彌彎彈強歸當錄徑後徹憂憑懷態慘慶憶戲戶擔據擴擺擾攜攝敗敘敵數斂斃斷無時晉曉暈暫術樸機殺雜權條楊樓標樣樹橋檔檢歡歲歷殘殼毀氣漢湯灣濕滿滅滾漁潛澤濟濤濫災愛爺牆獨獲環現瑪畫療發盜盤睜礦碼禮禍種穀積穩窩窮竄競筆築範簡糧糾紀紅約級紋納紙純紛組結絕統綠維綱網緊緒線練縣縱總織繞繪繫繼續罰羅職聽肅脅腦腳臉臺舊艦藝節莊華葉薦薩藥虛蟲補裝裡複見規視覺覽觀觸計訊討訓記講謝識譜議讓豈貝負財責賢敗貨質販貪貴貸費貼貿賀資賦賞賠賴贊趙趕跡踐車軌軒軟轉輪輯輸辦辭邊遙鄧郵醜醫釋鐘鐵鑑長門閃閉間閣隊陽陰陣階際陸陳險隨隱雙雞離難電靈靜頂頃項順須頓領頭顏風飛飯飲館馬駕駛駐驗驚魚鳥麥黃點齊齒龍"
)

_musicbrainz_lock = Lock()
_last_musicbrainz_request = 0.0


def search_track_metadata_candidates(query: str, limit: int = 5, country: str | None = None) -> dict[str, Any]:
    """Coordinates search track metadata candidates for the current Sonex flow.

    Typical use: Use this function when runtime code needs search track metadata candidates as part of a Sonex command, playback, auth, llm, or ui path.

    Example: search_track_metadata_candidates(query=..., limit=..., country=...) -> returns the value used by the surrounding Sonex flow.
    """
    clean_query = query.strip()
    bounded_limit = max(1, min(10, int(limit or 5)))
    if not clean_query:
        return {"candidates": [], "source_attempts": []}

    candidates: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    seen: set[str] = set()
    itunes_countries = _itunes_countries(clean_query, country)

    if itunes_countries:
        added, normalized_count, credible_count, searched_countries, errors = _collect_itunes_candidates(
            clean_query,
            bounded_limit,
            itunes_countries,
            candidates,
            seen,
        )
        if added or searched_countries or errors:
            attempts.append(
                _itunes_attempt(
                    added=added,
                    normalized_count=normalized_count,
                    credible_count=credible_count,
                    countries=searched_countries,
                    errors=errors,
                )
            )

    for provider, searcher in (
        ("deezer", lambda remaining: _search_deezer(clean_query, remaining)),
        ("musicbrainz", lambda remaining: _search_musicbrainz(clean_query, remaining)),
    ):
        if len(candidates) >= bounded_limit:
            break
        try:
            normalized = searcher(max(1, bounded_limit - len(candidates)))
        except HTTPError as exc:
            attempts.append(_error_attempt(provider, exc))
            continue
        except Exception as exc:
            attempts.append(_error_attempt(provider, exc))
            continue

        credible = [item for item in normalized if _is_credible(item)]
        added = 0
        for item in credible:
            key = _dedupe_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            candidates.append(item)
            added += 1
            if len(candidates) >= bounded_limit:
                break
        attempts.append(
            {
                "provider": provider,
                "status": "success" if added else "not_found",
                "candidate_count": len(normalized),
                "credible_count": len(credible),
                "message": f"{_provider_label(provider)} returned {added} candidate{'s' if added != 1 else ''}.",
            }
        )

    return {"candidates": candidates[:bounded_limit], "source_attempts": attempts}


def _collect_itunes_candidates(
    query: str,
    limit: int,
    countries: list[str],
    candidates: list[dict[str, Any]],
    seen: set[str],
) -> tuple[int, int, int, list[str], list[Exception]]:
    added = 0
    normalized_count = 0
    credible_count = 0
    searched_countries: list[str] = []
    errors: list[Exception] = []
    for country in countries:
        searched_countries.append(country)
        try:
            normalized = _search_itunes(query, limit, country)
        except Exception as exc:
            errors.append(exc)
            continue
        normalized_count += len(normalized)
        credible = [item for item in normalized if _is_credible(item)]
        credible_count += len(credible)
        for item in credible:
            key = _dedupe_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            item["_itunes_sequence"] = len(candidates)
            candidates.append(item)
            added += 1
    candidates.sort(key=_itunes_language_sort_key)
    for item in candidates:
        item.pop("_itunes_sequence", None)
    return added, normalized_count, credible_count, searched_countries, errors


def _itunes_language_sort_key(candidate: dict[str, Any]) -> tuple[int, int]:
    """Order iTunes editions as simplified Chinese, traditional Chinese, then English."""
    text = " ".join(str(candidate.get(field) or "") for field in ("name", "artist", "album"))
    country = str(candidate.get("itunes_country") or "").upper()
    if not _has_cjk(text):
        language_rank = 2
    elif any(character in TRADITIONAL_CHINESE_MARKERS for character in text) or country in {"TW", "HK"}:
        language_rank = 1
    else:
        language_rank = 0
    return language_rank, int(candidate.get("_itunes_sequence") or 0)


def _itunes_countries(query: str, country: str | None = None) -> list[str]:
    explicit = _country_code(country)
    if explicit:
        return [explicit]

    env_country = _country_code(os.environ.get("SONEX_ITUNES_COUNTRY"))
    if env_country:
        return [env_country]

    env_countries = _country_codes(os.environ.get("SONEX_ITUNES_COUNTRIES"))
    if env_countries:
        return env_countries

    return list(CJK_ITUNES_COUNTRIES if _has_cjk(query) else DEFAULT_ITUNES_COUNTRIES)


def _country_codes(value: Any) -> list[str]:
    seen: set[str] = set()
    countries: list[str] = []
    for part in str(value or "").split(","):
        code = _country_code(part)
        if code and code not in seen:
            seen.add(code)
            countries.append(code)
    return countries


def _country_code(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", text):
        return None
    return text


def _has_cjk(value: Any) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in str(value or ""))


def _itunes_attempt(
    *,
    added: int,
    normalized_count: int,
    credible_count: int,
    countries: list[str],
    errors: list[Exception],
) -> dict[str, Any]:
    if added:
        status = "success"
    elif errors and not normalized_count:
        status = "rate_limited" if all(isinstance(exc, HTTPError) and exc.code == 429 for exc in errors) else "error"
    else:
        status = "not_found"
    country_text = ", ".join(countries) if countries else "none"
    message = (
        f"iTunes searched {country_text} and returned {added} "
        f"candidate{'s' if added != 1 else ''}."
    )
    if status in {"rate_limited", "error"} and errors:
        message = f"iTunes searched {country_text}. {sanitize_error_message(errors[-1])}"
    attempt = {
        "provider": "itunes",
        "status": status,
        "candidate_count": max(0, int(normalized_count or 0)),
        "credible_count": max(0, int(credible_count or 0)),
        "countries": countries,
        "message": message,
    }
    if errors:
        attempt["error_count"] = len(errors)
    return attempt


def _search_itunes(query: str, limit: int, country: str) -> list[dict[str, Any]]:
    """Prepares search itunes for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs search itunes without duplicating the local rules.

    Example: _search_itunes(query=..., limit=..., country=...) -> returns the value used by the surrounding Sonex flow.
    """
    params = urllib.parse.urlencode(
        {
            "term": query,
            "country": country,
            "media": "music",
            "entity": "song",
            "limit": max(1, min(10, int(limit or 5))),
        }
    )
    payload = _json_request(f"{ITUNES_SEARCH_URL}?{params}", user_agent="Sonex/1.0")
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    return [_normalize_itunes(query, item, country=country) for item in results if isinstance(item, dict)]


def _search_deezer(query: str, limit: int) -> list[dict[str, Any]]:
    """Prepares search deezer for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs search deezer without duplicating the local rules.

    Example: _search_deezer(query=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    params = urllib.parse.urlencode({"q": query, "limit": max(1, min(10, int(limit or 5)))})
    payload = _json_request(f"{DEEZER_SEARCH_URL}?{params}", user_agent="Sonex/1.0")
    results = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    return [_normalize_deezer(query, item) for item in results if isinstance(item, dict)]


def _search_musicbrainz(query: str, limit: int) -> list[dict[str, Any]]:
    """Prepares search musicbrainz for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs search musicbrainz without duplicating the local rules.

    Example: _search_musicbrainz(query=..., limit=...) -> returns the value used by the surrounding Sonex flow.
    """
    params = urllib.parse.urlencode(
        {
            "query": query,
            "fmt": "json",
            "limit": max(1, min(10, int(limit or 5))),
        }
    )
    payload = _musicbrainz_json(f"{MUSICBRAINZ_SEARCH_URL}?{params}")
    recordings = payload.get("recordings") if isinstance(payload, dict) else None
    if not isinstance(recordings, list):
        return []
    return [_normalize_musicbrainz(query, item) for item in recordings if isinstance(item, dict)]


def _json_request(url: str, *, user_agent: str) -> dict[str, Any]:
    """Prepares json request for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs json request without duplicating the local rules.

    Example: _json_request(url=..., user_agent=...) -> returns the value used by the surrounding Sonex flow.
    """
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urlopen(request, timeout=6) as response:
        return json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))


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
    return _json_request(url, user_agent=MUSICBRAINZ_USER_AGENT)


def _normalize_itunes(query: str, item: dict[str, Any], *, country: str) -> dict[str, Any]:
    """Prepares normalize itunes for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize itunes without duplicating the local rules.

    Example: _normalize_itunes(query=..., item=...) -> returns the value used by the surrounding Sonex flow.
    """
    track_id = _text(item.get("trackId"))
    name = _text(item.get("trackName"))
    artist = _text(item.get("artistName"))
    album = _text(item.get("collectionName"))
    url = _text(item.get("trackViewUrl"))
    cover = _text(item.get("artworkUrl100") or item.get("artworkUrl60") or item.get("artworkUrl30"))
    return _candidate(
        query=query,
        metadata_source="itunes",
        provider="itunes",
        item_id=track_id,
        name=name,
        artist=artist,
        album=album,
        duration_ms=_int_ms(item.get("trackTimeMillis")),
        cover_url=cover,
        url=url,
        uri=f"itunes:track:{track_id}" if track_id else None,
        extra={
            "itunes_url": url,
            "itunes_country": country,
            "isrc": _text(item.get("isrc")),
            "preview_url": _text(item.get("previewUrl")),
            "release_date": _text(item.get("releaseDate")),
            "release_year": _release_year(item.get("releaseDate")),
            "album_id": _text(item.get("collectionId")),
            "artist_id": _text(item.get("artistId")),
            "provider_payload": item,
        },
    )


def _normalize_deezer(query: str, item: dict[str, Any]) -> dict[str, Any]:
    """Prepares normalize deezer for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize deezer without duplicating the local rules.

    Example: _normalize_deezer(query=..., item=...) -> returns the value used by the surrounding Sonex flow.
    """
    artist_obj = item.get("artist") if isinstance(item.get("artist"), dict) else {}
    album_obj = item.get("album") if isinstance(item.get("album"), dict) else {}
    track_id = _text(item.get("id"))
    url = _text(item.get("link"))
    return _candidate(
        query=query,
        metadata_source="deezer",
        provider="deezer",
        item_id=track_id,
        name=_text(item.get("title_short") or item.get("title")),
        artist=_text(artist_obj.get("name")),
        album=_text(album_obj.get("title")),
        duration_ms=_seconds_to_ms(item.get("duration")),
        cover_url=_text(album_obj.get("cover_xl") or album_obj.get("cover_big") or album_obj.get("cover_medium") or album_obj.get("cover")),
        url=url,
        uri=f"deezer:track:{track_id}" if track_id else None,
        extra={
            "deezer_url": url,
            "isrc": _text(item.get("isrc")),
            "preview_url": _text(item.get("preview")),
            "release_date": _text(item.get("release_date")),
            "release_year": _release_year(item.get("release_date")),
            "album_id": _text(album_obj.get("id")),
            "artist_id": _text(artist_obj.get("id")),
            "provider_payload": item,
        },
    )


def _normalize_musicbrainz(query: str, item: dict[str, Any]) -> dict[str, Any]:
    """Prepares normalize musicbrainz for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize musicbrainz without duplicating the local rules.

    Example: _normalize_musicbrainz(query=..., item=...) -> returns the value used by the surrounding Sonex flow.
    """
    recording_id = _text(item.get("id"))
    artist_names = _musicbrainz_artist_names(item.get("artist-credit"))
    artist = ", ".join(artist_names) if artist_names else None
    album = _musicbrainz_album(item.get("releases"))
    url = f"https://musicbrainz.org/recording/{recording_id}" if recording_id else None
    return _candidate(
        query=query,
        metadata_source="musicbrainz",
        provider="musicbrainz",
        item_id=recording_id,
        name=_text(item.get("title")),
        artist=artist,
        album=album,
        duration_ms=_int_ms(item.get("length")),
        cover_url=None,
        url=url,
        uri=f"musicbrainz:recording:{recording_id}" if recording_id else None,
        extra={
            "musicbrainz_recording_id": recording_id,
            "musicbrainz_url": url,
            "isrc": _first_text(item.get("isrcs")),
            "release_date": _musicbrainz_release_date(item.get("releases")),
            "release_year": _release_year(_musicbrainz_release_date(item.get("releases"))),
            "provider_payload": item,
        },
    )


def _candidate(
    *,
    query: str,
    metadata_source: str,
    provider: str,
    item_id: str | None,
    name: str | None,
    artist: str | None,
    album: str | None,
    duration_ms: int,
    cover_url: str | None,
    url: str | None,
    uri: str | None,
    extra: dict[str, Any],
) -> dict[str, Any]:
    """Prepares candidate for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs candidate without duplicating the local rules.

    Example: _candidate(query=..., metadata_source=..., provider=..., item_id=..., name=..., artist=..., album=..., duration_ms=..., cover_url=..., url=..., uri=..., extra=...) -> returns the value used by the surrounding Sonex flow.
    """
    artists = [artist] if artist else []
    candidate: dict[str, Any] = {
        "metadata_source": metadata_source,
        "provider": provider,
        "id": item_id,
        "name": name,
        "title": name,
        "artist": artist,
        "artists": artists,
        "album": album,
        "duration_ms": duration_ms,
        "album_cover_url": cover_url,
        "cover_url": cover_url,
        "url": url,
        "uri": uri,
        "original_query": query,
        "youtube_query": f"{artist or ''} {name or ''}".strip() or query,
        **extra,
    }
    return {key: value for key, value in candidate.items() if value not in (None, [], "")}


def _musicbrainz_artist_names(value: Any) -> list[str]:
    """Prepares musicbrainz artist names for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs musicbrainz artist names without duplicating the local rules.

    Example: _musicbrainz_artist_names(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, dict):
            artist_obj = item.get("artist") if isinstance(item.get("artist"), dict) else {}
            name = _text(item.get("name") or artist_obj.get("name"))
            if name:
                names.append(name)
    return names


def _musicbrainz_album(value: Any) -> str | None:
    """Prepares musicbrainz album for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs musicbrainz album without duplicating the local rules.

    Example: _musicbrainz_album(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, dict):
            title = _text(item.get("title"))
            if title:
                return title
    return None


def _musicbrainz_release_date(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, dict):
            date = _text(item.get("date"))
            if date:
                return date
    return None


def _first_text(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            text = _text(item)
            if text:
                return text
        return None
    return _text(value)


def _release_year(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    match = re.search(r"\d{4}", text)
    return match.group(0) if match else None


def _is_credible(item: dict[str, Any]) -> bool:
    """Prepares is credible for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs is credible without duplicating the local rules.

    Example: _is_credible(item=...) -> returns the value used by the surrounding Sonex flow.
    """
    return bool(_text(item.get("name") or item.get("title")) and _text(item.get("artist")))


def _dedupe_key(item: dict[str, Any]) -> str | None:
    """Prepares dedupe key for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs dedupe key without duplicating the local rules.

    Example: _dedupe_key(item=...) -> returns the value used by the surrounding Sonex flow.
    """
    name = _normalize_key_text(item.get("name") or item.get("title"))
    artist = _normalize_key_text(item.get("artist"))
    album = _normalize_key_text(item.get("album"))
    if not name or not artist:
        return None
    return "|".join((name, artist, album))


def _normalize_key_text(value: Any) -> str:
    """Prepares normalize key text for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize key text without duplicating the local rules.

    Example: _normalize_key_text(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    return " ".join(re.findall(r"[\w\u4e00-\u9fff]+", str(value or "").casefold()))


def _text(value: Any) -> str | None:
    """Prepares text for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs text without duplicating the local rules.

    Example: _text("  song  ") -> "song"; _text("") -> None.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_ms(value: Any) -> int:
    """Prepares int ms for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs int ms without duplicating the local rules.

    Example: _int_ms(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _seconds_to_ms(value: Any) -> int:
    """Prepares seconds to ms for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs seconds to ms without duplicating the local rules.

    Example: _seconds_to_ms(value=...) -> returns the value used by the surrounding Sonex flow.
    """
    try:
        return max(0, int(float(value or 0) * 1000))
    except (TypeError, ValueError):
        return 0


def _error_attempt(provider: str, exc: Exception) -> dict[str, Any]:
    """Prepares error attempt for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs error attempt without duplicating the local rules.

    Example: _error_attempt(provider=..., exc=...) -> returns the value used by the surrounding Sonex flow.
    """
    status = "rate_limited" if isinstance(exc, HTTPError) and exc.code == 429 else "error"
    message = f"{_provider_label(provider)} rate limit reached." if status == "rate_limited" else sanitize_error_message(exc)
    return {
        "provider": provider,
        "status": status,
        "candidate_count": 0,
        "credible_count": 0,
        "message": message,
    }


def _provider_label(provider: str) -> str:
    """Prepares provider label for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs provider label without duplicating the local rules.

    Example: _provider_label(provider=...) -> returns the value used by the surrounding Sonex flow.
    """
    return {"itunes": "iTunes", "deezer": "Deezer", "musicbrainz": "MusicBrainz"}.get(provider, provider.title())

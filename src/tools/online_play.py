from __future__ import annotations

import hashlib
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yt_dlp

from src.log import sonex_home
from src.tools.local_play import check_player
from src.tools.cover_sources import resolve_online_cover
from src.tools.player_permission import (
    build_player_confirm_result,
    is_player_allowed,
)
from src.tools.playback_controller import start_local_playback
from src.tools.registry import registry, Params
from src.tools.result import ToolResult
from src.tools.song_cache import resolve_cached_song, upsert_cached_song

LIVE_TERMS = ("live", "concert", "session", "现场", "演唱会")
LOW_RELEVANCE_TERMS = ("cover", "tutorial", "reaction", "karaoke", "翻唱", "教程", "伴奏")
OFFICIAL_TERMS = ("official audio", "official music video", "official video", "official mv")
NOISY_MEDIA_TERMS = (
    "tv",
    "television",
    "show",
    "variety",
    "interview",
    "reaction",
    "karaoke",
    "tutorial",
    "综艺",
    "电视",
    "节目",
    "访谈",
    "教程",
    "伴奏",
)
COVER_TERMS = ("cover", "翻唱")
QUERY_FILLER_TERMS = {"the", "a", "an"}


def _song_cache_root(cache_root: Path | None = None) -> Path:
    return cache_root or sonex_home() / "cache" / "songs"


def _audio_cache_dir(cache_root: Path | None = None) -> Path:
    return _song_cache_root(cache_root) / "audio"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _joined_text(value: Any) -> str | None:
    if isinstance(value, list):
        parts = [_text(item) for item in value]
        return ", ".join(part for part in parts if part) or None
    return _text(value)


def _non_placeholder_text(value: Any) -> str | None:
    text = _joined_text(value)
    if text in {None, "-"}:
        return None
    return text


def _duration_ms(value: Any) -> int:
    try:
        return max(0, int(float(value or 0) * 1000))
    except (TypeError, ValueError):
        return 0


def _count(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _words(value: str) -> list[str]:
    return re.findall(r"[\w\u4e00-\u9fff]+", value.casefold())


def _normalized_rank_text(value: str) -> str:
    return " ".join(_words(value))


def _query_terms(query: str) -> list[str]:
    terms = _words(query)
    return [term for term in terms if term not in QUERY_FILLER_TERMS and term not in LIVE_TERMS]


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    text = value.casefold()
    return any(term in text for term in terms)


def _variant_type(query: str, info: dict[str, Any]) -> str:
    title = _text(info.get("track") or info.get("title") or info.get("fulltitle") or "") or ""
    channel = _text(info.get("channel") or info.get("uploader") or "") or ""
    combined = f"{title} {channel}".casefold()
    if _contains_any(combined, LIVE_TERMS):
        return "live"
    if _contains_any(combined, OFFICIAL_TERMS) or " - topic" in combined or "official" in channel.casefold() or "vevo" in channel.casefold():
        return "official_original"
    return "other"


def _rank_title(info: dict[str, Any]) -> str:
    return _text(info.get("track") or info.get("title") or info.get("fulltitle") or "") or ""


def _rank_channel(info: dict[str, Any]) -> str:
    return _text(info.get("channel") or info.get("uploader") or "") or ""


def _rank_artist(info: dict[str, Any]) -> str:
    return (
        _non_placeholder_text(info.get("artist"))
        or _non_placeholder_text(info.get("artists"))
        or _non_placeholder_text(info.get("creator"))
        or _non_placeholder_text(info.get("creators"))
        or ""
    )


def _rank_haystack(info: dict[str, Any]) -> str:
    return " ".join(
        str(value or "")
        for value in (
            info.get("track"),
            info.get("title"),
            info.get("fulltitle"),
            info.get("artist"),
            info.get("artists"),
            info.get("creator"),
            info.get("uploader"),
            info.get("channel"),
        )
    )


def _similarity_score(query: str, info: dict[str, Any]) -> int:
    query_norm = _normalized_rank_text(query)
    if not query_norm:
        return 0

    title_norm = _normalized_rank_text(_rank_title(info))
    artist_norm = _normalized_rank_text(_rank_artist(info) or _rank_channel(info))
    variants = [title_norm]
    if artist_norm and title_norm:
        variants.extend((f"{artist_norm} {title_norm}", f"{title_norm} {artist_norm}"))
    best_ratio = max((SequenceMatcher(None, query_norm, value).ratio() for value in variants if value), default=0.0)

    terms = _query_terms(query)
    haystack_words = set(_words(_rank_haystack(info)))
    coverage = sum(1 for term in terms if term in haystack_words) / len(terms) if terms else 0.0
    return round((best_ratio * 0.6 + coverage * 0.4) * 100)


def _clean_title_match(query: str, info: dict[str, Any], similarity: int) -> bool:
    title = _rank_title(info)
    if similarity < 70:
        return False
    if _contains_any(title, LIVE_TERMS + LOW_RELEVANCE_TERMS + NOISY_MEDIA_TERMS):
        return False
    return " - " in title or " – " in title or " — " in title or similarity >= 86


def _quality_label(query: str, info: dict[str, Any], variant: str, similarity: int) -> str:
    combined = f"{_rank_title(info)} {_rank_channel(info)}".casefold()
    live_requested = _contains_any(query, LIVE_TERMS)
    if variant == "live":
        return "live"
    if variant == "official_original":
        return "official_original"
    if not live_requested and _contains_any(combined, COVER_TERMS):
        return "cover_like"
    if not live_requested and _contains_any(combined, NOISY_MEDIA_TERMS):
        return "noisy_media"
    if _clean_title_match(query, info, similarity):
        return "clean_audio_match"
    return "other"


def _popularity_tiebreaker(popularity: int) -> int:
    return round(math.log10(max(0, popularity) + 1) * 1000)


def _relevance_score(query: str, info: dict[str, Any]) -> int:
    terms = _query_terms(query)
    if not terms:
        return 0
    haystack = _rank_haystack(info).casefold()
    return sum(1 for term in terms if term in haystack)


def _popularity_score(info: dict[str, Any]) -> int:
    view_count = _count(info.get("view_count"))
    like_count = _count(info.get("like_count"))
    comment_count = _count(info.get("comment_count"))
    repost_count = _count(info.get("repost_count"))
    return view_count + like_count * 20 + comment_count * 5 + repost_count * 10


def _rank_reason(variant: str, popularity: int, relevance: int, similarity: int, quality: str) -> str:
    label = {
        "official_original": "official original",
        "live": "live version",
        "other": "other match",
    }.get(variant, "other match")
    return f"{label}; quality={quality}; similarity={similarity}; popularity={popularity}; relevance={relevance}"


def _should_keep_candidate(query: str, info: dict[str, Any]) -> bool:
    title = _rank_title(info)
    if not title:
        return bool(_text(info.get("id")) or _webpage_url(info))
    if _relevance_score(query, info) <= 0:
        return False
    if not _contains_any(query, LOW_RELEVANCE_TERMS) and _contains_any(title, LOW_RELEVANCE_TERMS):
        return False
    return True


def _best_thumbnail(info: dict[str, Any]) -> str | None:
    direct = _text(info.get("thumbnail"))
    if direct:
        return direct

    thumbnails = info.get("thumbnails")
    if not isinstance(thumbnails, list):
        return None
    candidates = [item for item in thumbnails if isinstance(item, dict) and item.get("url")]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (item.get("width") or 0) * (item.get("height") or 0),
        reverse=True,
    )
    return _text(candidates[0].get("url"))


def _audio_stream_url(info: dict[str, Any]) -> str:
    stream_url = _text(info.get("url"))
    if stream_url:
        return stream_url

    formats = info.get("formats") or []
    audio_formats = [
        item for item in formats
        if isinstance(item, dict)
        and item.get("url")
        and item.get("acodec") not in (None, "none")
        and item.get("vcodec") in (None, "none")
    ]
    if not audio_formats:
        raise RuntimeError("No playable audio-only format found.")

    audio_formats.sort(key=lambda item: (item.get("abr") or 0, item.get("tbr") or 0), reverse=True)
    return str(audio_formats[0]["url"])


def _webpage_url(info: dict[str, Any]) -> str | None:
    url = _text(info.get("webpage_url") or info.get("original_url"))
    if url:
        return url
    video_id = _text(info.get("id"))
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return None


def _youtube_cache_id(info: dict[str, Any]) -> str:
    video_id = _text(info.get("youtube_id") or info.get("id"))
    if video_id:
        return f"youtube_{video_id}"
    url = _webpage_url(info) or _text(info.get("url")) or ""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"youtube_{digest}"


def _cached_audio_item(cache_id: str, *, cache_root: Path | None = None) -> dict[str, Any] | None:
    try:
        item = resolve_cached_song(cache_id, cache_root=cache_root)
    except Exception:
        return None
    audio_path = _text(item.get("audio_path"))
    if audio_path and Path(audio_path).expanduser().exists():
        item["stream_url"] = audio_path
        item["cached"] = True
        return item
    return None


def _normalize_youtube_info(query: str, info: dict[str, Any], stream_url: str | None = None) -> dict[str, Any]:
    title = _text(info.get("track") or info.get("title") or info.get("fulltitle") or query) or query
    artist = (
        _non_placeholder_text(info.get("artist"))
        or _non_placeholder_text(info.get("artists"))
        or _non_placeholder_text(info.get("creator"))
        or _non_placeholder_text(info.get("creators"))
        or _non_placeholder_text(info.get("uploader"))
        or _non_placeholder_text(info.get("channel"))
        or "-"
    )
    album = _text(info.get("album") or info.get("playlist_title") or info.get("series"))
    cover_url = _text(info.get("official_album_cover_url") or info.get("provider_album_cover_url"))
    webpage_url = _webpage_url(info)
    youtube_id = _text(info.get("youtube_id") or info.get("id"))
    cache_id = _youtube_cache_id({**info, "youtube_id": youtube_id})
    variant = _variant_type(query, info)
    popularity = _popularity_score(info)
    relevance = _relevance_score(query, info)
    similarity = _similarity_score(query, info)
    quality = _quality_label(query, info, variant, similarity)
    return {
        "provider": "youtube",
        "id": youtube_id,
        "youtube_id": youtube_id,
        "cache_id": cache_id,
        "query": query,
        "name": title,
        "title": title,
        "artist": artist,
        "artists": [artist] if artist and artist != "-" else [],
        "album": album or "-",
        "duration_ms": _duration_ms(info.get("duration")),
        "album_cover_url": cover_url,
        "cover_url": cover_url,
        "url": webpage_url,
        "webpage_url": webpage_url,
        "stream_url": stream_url,
        "variant_type": variant,
        "popularity_score": popularity,
        "relevance_score": relevance,
        "similarity_score": similarity,
        "quality_label": quality,
        "rank_reason": _rank_reason(variant, popularity, relevance, similarity, quality),
        "raw_view_count": _count(info.get("view_count")),
        "raw_like_count": _count(info.get("like_count")),
        "is_playing": True,
    }


def _rank_youtube_candidates(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    live_requested = _contains_any(query, LIVE_TERMS)
    quality_priority = {
        "official_original": 4,
        "clean_audio_match": 3,
        "live": 2,
        "other": 1,
        "cover_like": -2,
        "noisy_media": -3,
    }
    if live_requested:
        quality_priority = {
            "live": 4,
            "official_original": 3,
            "clean_audio_match": 2,
            "other": 1,
            "cover_like": 0,
            "noisy_media": -1,
        }

    def score(pair: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int, int]:
        index, candidate = pair
        quality = str(candidate.get("quality_label") or "other")
        noisy_penalty = 25 if quality in {"noisy_media", "cover_like"} and not live_requested else 0
        similarity = max(0, int(candidate.get("similarity_score") or 0) - noisy_penalty)
        popularity = _popularity_tiebreaker(int(candidate.get("popularity_score") or 0))
        relevance = int(candidate.get("relevance_score") or 0)
        return (
            similarity,
            quality_priority.get(quality, 0),
            relevance,
            popularity,
            -index,
        )

    indexed = list(enumerate(candidates))
    indexed.sort(key=score, reverse=True)
    return [candidate for _, candidate in indexed]


def search_youtube_songs(query: str, limit: int = 5, *, cache_root: Path | None = None) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(10, int(limit or 5)))
    search_limit = min(50, max(bounded_limit, bounded_limit * 8))
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        payload = ydl.extract_info(f"ytsearch{search_limit}:{query}", download=False)

    if not isinstance(payload, dict):
        raise RuntimeError("Invalid response returned.")

    entries = payload.get("entries") or []
    candidates: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not _should_keep_candidate(query, entry):
            continue
        candidate = _normalize_youtube_info(query, entry, None)
        cached = _cached_audio_item(str(candidate["cache_id"]), cache_root=cache_root)
        candidate["cached"] = cached is not None
        if cached:
            candidate["audio_path"] = cached.get("audio_path")
            candidate["audio_ext"] = cached.get("audio_ext")
        candidates.append(candidate)
    if not candidates:
        raise RuntimeError("No valid matches found.")
    return _rank_youtube_candidates(query, candidates)[:bounded_limit]


def _downloaded_filepath(info: dict[str, Any], fallback: Path) -> Path:
    downloads = info.get("requested_downloads")
    if isinstance(downloads, list):
        for item in downloads:
            if isinstance(item, dict):
                path = _text(item.get("filepath") or item.get("_filename"))
                if path:
                    return Path(path).expanduser()
    ext = _text(info.get("ext")) or fallback.suffix.lstrip(".") or "webm"
    return fallback.with_suffix(f".{ext}")


def download_youtube_candidate(candidate: dict[str, Any], *, cache_root: Path | None = None) -> dict[str, Any]:
    cache_id = _text(candidate.get("cache_id")) or _youtube_cache_id(candidate)
    cached = _cached_audio_item(cache_id, cache_root=cache_root)
    if cached:
        return cached

    webpage_url = _text(candidate.get("webpage_url") or candidate.get("url"))
    if not webpage_url:
        raise RuntimeError("Unable to resolve a playable YouTube URL.")

    audio_dir = _audio_cache_dir(cache_root)
    audio_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(audio_dir / f"{cache_id}.%(ext)s")
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(webpage_url, download=True)
    if not isinstance(info, dict):
        raise RuntimeError("Invalid response returned.")
    if "formats" in info:
        _audio_stream_url(info)

    merged = {**candidate, **info}
    for cover_key in ("official_album_cover_url", "provider_album_cover_url"):
        if candidate.get(cover_key):
            merged[cover_key] = candidate[cover_key]
    merged["webpage_url"] = _webpage_url(merged) or webpage_url
    audio_path = _downloaded_filepath(merged, audio_dir / f"{cache_id}.webm")
    audio_ext = audio_path.suffix.lstrip(".") or _text(merged.get("ext")) or "webm"
    item = {
        **_normalize_youtube_info(str(candidate.get("query") or merged.get("query") or merged.get("title") or ""), merged, str(audio_path)),
        "cache_id": cache_id,
        "youtube_id": _text(merged.get("youtube_id") or merged.get("id")),
        "audio_path": str(audio_path),
        "audio_ext": audio_ext,
        "stream_url": str(audio_path),
        "cached": True,
    }
    cover = resolve_online_cover(item)
    if cover:
        item["album_cover_url"] = cover["cover_source"]
        item["cover_url"] = cover.get("cover_url") or cover["cover_source"]
        item["cover_source"] = cover["cover_source"]
        item["cover_source_type"] = cover["source_type"]
    upsert_cached_song(item, cache_root=cache_root)
    return item


def play_youtube_candidate(
    candidate: dict[str, Any],
    *,
    player: str = "auto",
    cache_root: Path | None = None,
) -> dict[str, Any]:
    try:
        data = download_youtube_candidate(candidate, cache_root=cache_root)
    except Exception as exc:
        message = str(exc)
        error_code = "NO_PLAYABLE_AUDIO" if "No playable audio" in message else "YOUTUBE_RESOLVE_FAILED"
        return ToolResult.fail(
            tool="play_youtube_song",
            message=message,
            error_code=error_code,
            data={"query": candidate.get("query"), "player": player, "method": "online_play", "provider": "youtube"},
        ).to_dict()

    if player != "auto" and not check_player(player):
        return ToolResult.error(
            tool="play_youtube_song",
            message=f"Player '{player}' is not ready.",
            error_code="PLAYER_MISSED",
            data={**data, "player": player, "method": "online_play"},
        )

    audio_path = str(data["audio_path"])
    if player == "auto":
        cmd = ["sonex-local-playback", "auto", audio_path]
    elif player == "mpv":
        cmd = ["mpv", "--no-video", audio_path]
    elif player == "cvlc":
        cmd = ["cvlc", "--no-video", audio_path]
    else:
        cmd = [player, "--play-and-exit", audio_path]
    data = {**data, "player": player, "method": "online_play", "source": "youtube"}
    success_message = f"Playing '{data.get('query') or data.get('name')}' online started."

    if not is_player_allowed(player):
        return build_player_confirm_result(
            tool="play_youtube_song",
            player=player,
            cmd=cmd,
            success_message=success_message,
            data={
                **data,
                "playback_source_url": audio_path,
                "playback_source": "youtube",
                "playback_metadata": data,
            },
        )

    return start_local_playback(
        tool="play_youtube_song",
        source_url=audio_path,
        source="youtube",
        metadata=data,
        player=player,
        success_message=success_message,
    )


# 在youtube上搜索歌曲并解析音频流
def resolve_youtube_song(query: str) -> dict[str, Any]:
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        payload = ydl.extract_info(f"ytsearch1:{query}", download=False)

    if not isinstance(payload, dict):
        raise RuntimeError("Invalid response returned.")

    entries = payload.get("entries") or []
    if not entries or not isinstance(entries[0], dict):
        raise RuntimeError("No valid matches found.")
    first_entry = entries[0]

    video_id = first_entry.get("id")
    webpage_url = first_entry.get("webpage_url")

    if not webpage_url and video_id:
        webpage_url = f"https://www.youtube.com/watch?v={video_id}"

    if not webpage_url:
        raise RuntimeError("Unable to resolve a playable YouTube URL.")

    stream_opts = {
        "quiet": True,  # 减少控制台输出
        "no_warnings": True,  # 不打印warning日志信息
        "noplaylist": True,  # 搜索结果关联playlist取单条视频
        "format": "bestaudio/best",  # 优先最佳音频流
        "skip_download": True,  # 只解析不下载
    }

    with yt_dlp.YoutubeDL(stream_opts) as ydl:
        info = ydl.extract_info(webpage_url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError("Invalid response returned.")

    merged_info = {**first_entry, **info}
    merged_info["webpage_url"] = _webpage_url(merged_info) or webpage_url
    stream_url = _audio_stream_url(merged_info)
    return _normalize_youtube_info(query, merged_info, stream_url)


def search_and_resolve_song(query: str) -> str:
    candidate = search_youtube_songs(query, limit=1)[0]
    return str(download_youtube_candidate(candidate)["stream_url"])


def play_youtube_song(query: str, player: str = "auto", cache_root: Path | None = None) -> dict[str, Any]:
    try:
        candidate = search_youtube_songs(query, limit=1, cache_root=cache_root)[0]
    except Exception as exc:
        message = str(exc)
        error_code = "NO_PLAYABLE_AUDIO" if "No playable audio" in message else "YOUTUBE_RESOLVE_FAILED"
        return ToolResult.fail(
            tool="play_youtube_song",
            message=message,
            error_code=error_code,
            data={"query": query, "player": player, "method": "online_play", "provider": "youtube"},
        ).to_dict()
    return play_youtube_candidate(candidate, player=player, cache_root=cache_root)

registry.register(
    name="play_youtube_song",
    type="player",
    description="Play a resolved audio extract from youtube via mpv music player.",
    parameters=Params(
        type="object",
        properties={
            "query": {"type": "string", "description": "The song name or related key words."},
        },
        required=["query"],
    ),
    fn=play_youtube_song,
    enable=True,
    read_only=False,
    required_confirm=False,
)

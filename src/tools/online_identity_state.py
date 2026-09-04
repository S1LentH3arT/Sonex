"""Pure identity and query normalization rules for online audio candidates."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

LIVE_TERMS = ("live", "concert", "session", "现场", "現場", "演唱会", "演唱會", "剧场", "劇場")
LOW_RELEVANCE_TERMS = ("cover", "tutorial", "reaction", "karaoke", "翻唱", "教程", "伴奏")
OFFICIAL_TERMS = ("official audio", "official music video", "official video", "official mv")
NOISY_MEDIA_TERMS = ("tv", "television", "show", "variety", "interview", "reaction", "karaoke", "tutorial", "综艺", "綜藝", "电视", "電視", "卫视", "衛視", "节目", "節目", "访谈", "教程", "伴奏")
COVER_TERMS = ("cover", "翻唱")
QUERY_FILLER_TERMS = {"the", "a", "an"}
IGNORABLE_TITLE_SUFFIX_RE = re.compile(
    r"(?:\s*[\[(\-{]\s*)?(?:official(?:\s+(?:audio|music\s+video|video|mv))?|lyrics?|lyric\s+video|(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?)(?:\s*[])}]\s*)?$",
    re.IGNORECASE,
)
FEATURED_ARTIST_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)
FEATURED_TITLE_RE = re.compile(r"\s*(?:[\[(（【]\s*)?(?:feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _joined_text(value: Any) -> str | None:
    if isinstance(value, list):
        parts = [_text(item) for item in value]
        return ", ".join(part for part in parts if part) or None
    return _text(value)


def _non_placeholder_text(value: Any) -> str | None:
    normalized = _joined_text(value)
    return None if normalized in {None, "-"} else normalized


def identity_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = "".join(character if character.isalnum() else " " for character in text)
    return " ".join(text.split())


def has_cjk(value: Any) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in str(value or ""))


def mostly_latin(value: Any) -> bool:
    letters = [character for character in str(value or "") if character.isalpha()]
    if not letters:
        return False
    latin = [character for character in letters if "LATIN" in unicodedata.name(character, "")]
    return len(latin) / len(letters) >= 0.7


def identity_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = FEATURED_TITLE_RE.sub("", text).strip()
    previous = None
    while text and text != previous:
        previous = text
        text = IGNORABLE_TITLE_SUFFIX_RE.sub("", text).strip()
    return identity_text(text)


def identity_title_text(identity: dict[str, Any]) -> str:
    title = unicodedata.normalize("NFKC", str(identity.get("title") or "")).strip()
    artist = unicodedata.normalize("NFKC", str(identity.get("artist") or "")).strip()
    if artist:
        title = re.sub(rf"^\s*{re.escape(artist)}\s*[-–—:|]\s*", "", title, count=1, flags=re.IGNORECASE)
    return identity_title(title)


def identity_artist(item: dict[str, Any]) -> str:
    artists = item.get("artists")
    if isinstance(artists, list) and artists:
        primary = _non_placeholder_text(artists[0])
        if primary:
            return primary
    artist = _non_placeholder_text(item.get("artist")) or ""
    return FEATURED_ARTIST_RE.sub("", artist).strip()


def identity_artist_text(value: Any) -> str:
    return identity_text(FEATURED_ARTIST_RE.sub("", str(value or "")).strip())


def words(value: str) -> list[str]:
    return re.findall(r"[\w\u4e00-\u9fff]+", value.casefold())


def normalized_rank_text(value: str) -> str:
    return " ".join(words(value))


def query_terms(query: str) -> list[str]:
    return [term for term in words(query) if term not in QUERY_FILLER_TERMS and term not in LIVE_TERMS]


def contains_any(value: str, terms: tuple[str, ...]) -> bool:
    lowered = value.casefold()
    return any(term in lowered for term in terms)

"""Pure normalization rules shared by music identity matching."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

FEAT_RE = re.compile(r"\b(?:feat\.?|ft\.?|featuring)\b", re.IGNORECASE)
BRACKET_RE = re.compile(r"[\[\](){}（）【】]+")
PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)
VERSION_TAGS = {
    "live",
    "remix",
    "cover",
    "karaoke",
    "acoustic",
    "instrumental",
    "demo",
    "现场",
    "翻唱",
    "伴奏",
}
DISPLAY_SUFFIX_RE = re.compile(
    r"(?:\s+)?(?:official(?:\s+(?:audio|music\s+video|video|mv))?|lyrics?|lyric\s+video|"
    r"(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?)$",
    re.IGNORECASE,
)
SIMPLIFIED_TRADITIONAL_PAIRS = {
    "爱": "愛",
    "动": "動",
    "发": "發",
    "国": "國",
    "后": "後",
    "来": "來",
    "乐": "樂",
    "丽": "麗",
    "录": "錄",
    "梦": "夢",
    "声": "聲",
    "态": "態",
    "听": "聽",
    "万": "萬",
    "为": "為",
    "游": "遊",
    "园": "園",
    "与": "與",
    "云": "雲",
    "词": "詞",
}
SIMPLIFIED_TO_TRADITIONAL = str.maketrans(SIMPLIFIED_TRADITIONAL_PAIRS)
TRADITIONAL_TO_SIMPLIFIED = str.maketrans({v: k for k, v in SIMPLIFIED_TRADITIONAL_PAIRS.items()})


def normalize_music_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = FEAT_RE.sub(" feat ", text)
    text = BRACKET_RE.sub(" ", text)
    text = PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def simplified_traditional_variants(value: str) -> set[str]:
    text = str(value or "")
    return {text, text.translate(SIMPLIFIED_TO_TRADITIONAL), text.translate(TRADITIONAL_TO_SIMPLIFIED)}


def version_tags(value: Any) -> set[str]:
    normalized = normalize_music_text(value)
    found = {tag for tag in VERSION_TAGS if tag in normalized.split() or tag in normalized}
    if "official" in normalized or "audio" in normalized or "video" in normalized:
        found.discard("official")
    return found


def display_title(value: str) -> str:
    text = normalize_music_text(FEAT_RE.split(str(value or ""), maxsplit=1)[0])
    previous = None
    while text and text != previous:
        previous = text
        text = DISPLAY_SUFFIX_RE.sub("", text).strip()
    return text


def primary_artist(value: str) -> str:
    return FEAT_RE.split(str(value or ""), maxsplit=1)[0].strip()

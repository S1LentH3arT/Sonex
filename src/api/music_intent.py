"""Music intent support for fastapi and websocket routing for the sonex runtime.

Implements the music_intent module responsibilities used by Sonex runtime flows.
Key public entry points include MusicIntentRoute, MusicIntentDecision, classify_music_intent_fast, classify_music_intent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

from src.llm.transport import ChatRequest
from src.thinking.config import ThinkingConfig


class MusicIntentRoute(str, Enum):
    """Represents music intent route.

    Encapsulates music intent route data and behavior used by Sonex runtime flows. Extends str, enum semantics.
    """
    EXPLICIT_PLAY = "explicit_play"
    CONFIRM_TRACK_PLAY = "confirm_track_play"
    RECOMMEND = "recommend"
    GENERAL = "general"


@dataclass(frozen=True)
class MusicIntentDecision:
    """Represents music intent decision.

    Encapsulates music intent decision data and behavior used by Sonex runtime flows.
    """
    route: MusicIntentRoute
    query: str | None = None
    recommendation_index: int | None = None
    confidence: float = 0.0

_CHINESE_NUMBERS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _recommendation_reference(text: str) -> int | None:
    """Prepares recommendation reference for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs recommendation reference without duplicating the local rules.

    Example: _recommendation_reference(text=...) -> returns the value used by the surrounding Sonex flow.
    """
    if not any(marker in text for marker in ("第", "刚才", "推荐")):
        return None
    match = re.search(r"第\s*(\d+)\s*首", text)
    if match:
        return int(match.group(1))
    match = re.search(r"第?\s*([一二两三四五六七八九十])\s*首", text)
    if match:
        return _CHINESE_NUMBERS[match.group(1)]
    return None


def _explicit_play_fast_path(text: str) -> MusicIntentDecision | None:
    """Prepares explicit play fast path for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs explicit play fast path without duplicating the local rules.

    Example: _explicit_play_fast_path(text=...) -> returns the value used by the surrounding Sonex flow.
    """
    stripped = text.strip()
    lowered = stripped.lower()

    reference = _recommendation_reference(stripped)
    if reference is not None:
        return MusicIntentDecision(
            route=MusicIntentRoute.EXPLICIT_PLAY,
            recommendation_index=reference,
            confidence=1.0,
        )

    en_patterns = (r"\bplay\b", r"\blisten to\b", r"\bdance\b",)
    zh_markers = ("放一首", "来一首", "放一下", "放首", "来首", "想听", "听点", "听首", "听一下", "听一首", "来点",
                  "放点", "听", "放")
    for pattern in en_patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        query = stripped[match.end():].strip(" \t\r\n,.!?:;")
        if query:
            return MusicIntentDecision(
                route=MusicIntentRoute.EXPLICIT_PLAY,
                query=query,
                confidence=1.0,
            )

    for marker in zh_markers:
        idx = stripped.find(marker)
        if idx == -1:
            continue
        query = stripped[idx + len(marker):].strip(" \t\r\n,，.。!！?？:：;；")
        if query:
            return MusicIntentDecision(
                route=MusicIntentRoute.EXPLICIT_PLAY,
                query=query,
                confidence=1.0,
            )
    return None


def classify_music_intent_fast(text: str) -> MusicIntentDecision | None:
    """Coordinates classify music intent fast for the current Sonex flow.

    Typical use: Use this function when runtime code needs classify music intent fast as part of a Sonex command, playback, auth, llm, or ui path.

    Example: classify_music_intent_fast(text=...) -> returns the value used by the surrounding Sonex flow.
    """
    return _explicit_play_fast_path(text)


def classify_music_intent(text: str) -> MusicIntentDecision:
    """Coordinates classify music intent for the current Sonex flow.

    Typical use: Use this function when runtime code needs classify music intent as part of a Sonex command, playback, auth, llm, or ui path.

    Example: classify_music_intent(text=...) -> returns the value used by the surrounding Sonex flow.
    """
    fast_path = classify_music_intent_fast(text)
    if fast_path is not None:
        return fast_path

    prompt = (
        "Classify the user's music intent. Return JSON only with keys route, query, "
        "recommendation_index, confidence. route must be explicit_play, confirm_track_play, "
        "recommend, or general. explicit_play means an immediate playback command. "
        "confirm_track_play means interest in one specific track without an explicit command. "
        "recommend means asking for songs or expressing broad artist/genre interest. "
        "Questions about lyrics, meaning, history, or facts are general. query should be a concise "
        "track or recommendation query. confidence is between 0 and 1.\n"
        f"user_input: {text.strip()}"
    )
    try:
        response = ThinkingConfig.get_client().generate(
            ChatRequest(
                model=ThinkingConfig.get_model(),
                messages=[
                    {"role": "system", "content": "You are a strict music intent classifier."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=160,
            )
        )
        data = json.loads(str(response.output_text or ""))
        route = MusicIntentRoute(str(data.get("route") or "general"))
        confidence = float(data.get("confidence") or 0.0)
        if confidence < 0.75:
            raise ValueError("low confidence")
        query = str(data.get("query") or "").strip() or None
        index_value = data.get("recommendation_index")
        recommendation_index = int(index_value) if index_value is not None else None
        if route in {MusicIntentRoute.EXPLICIT_PLAY, MusicIntentRoute.CONFIRM_TRACK_PLAY, MusicIntentRoute.RECOMMEND} and not (query or recommendation_index):
            raise ValueError("missing classified query")
        return MusicIntentDecision(route, query, recommendation_index, confidence)
    except Exception:
        return MusicIntentDecision(MusicIntentRoute.GENERAL)

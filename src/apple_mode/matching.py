"""Strict Apple catalog candidate ranking within one authoritative storefront."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.tools.music_matching import (
    AliasResolver,
    MatchDecision,
    audio_result_from_candidate,
    canonical_track_from_metadata,
    normalize_music_text,
    score_audio_match,
    simplified_traditional_variants,
    version_tags,
)

FIELD_RE = re.compile(
    r"(?:^|\s)(track|title|artist|album)\s*:\s*(.*?)(?=\s+(?:track|title|artist|album|source)\s*:|$)",
    re.IGNORECASE,
)


class AppleCandidateDecision(StrEnum):
    AUTO = "auto"
    PICKER = "picker"
    CONFIRM = "confirm"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class RankedAppleCandidates:
    decision: AppleCandidateDecision
    candidates: tuple[dict[str, Any], ...]
    reason: str


def parse_apple_query(query: str) -> dict[str, str]:
    fields = {match.group(1).casefold(): match.group(2).strip() for match in FIELD_RE.finditer(query)}
    title = fields.get("track") or fields.get("title") or ""
    if fields:
        return {
            "title": title,
            "artist": fields.get("artist", ""),
            "album": fields.get("album", ""),
        }
    return {"title": query.strip(), "artist": "", "album": ""}


def rank_apple_candidates(query: str, candidates: list[dict[str, Any]]) -> RankedAppleCandidates:
    target_fields = parse_apple_query(query)
    target = canonical_track_from_metadata(target_fields)
    resolver = AliasResolver.load()
    accepted: list[tuple[int, dict[str, Any]]] = []
    review: list[tuple[int, dict[str, Any]]] = []
    contained_identity: list[dict[str, Any]] = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_result = audio_result_from_candidate(candidate)
        score_target = target
        if (
            not target.artist
            and _contains_equivalent(query, candidate_result.title)
            and _contains_equivalent(query, candidate_result.artist)
        ):
            score_target = canonical_track_from_metadata(
                {
                    "title": candidate_result.title,
                    "artist": candidate_result.artist,
                    "album": candidate_result.album if _contains_equivalent(query, candidate_result.album) else "",
                }
            )
        score = score_audio_match(score_target, candidate_result, resolver)
        enriched = {**candidate, "apple_match": score.to_dict()}
        if target.album and candidate.get("album") and not resolver.matches("album", target.album, candidate.get("album")):
            continue
        if version_tags(target.title) != version_tags(candidate.get("name") or candidate.get("title")):
            continue
        if score.decision is MatchDecision.ACCEPT:
            accepted.append((score.total_score, enriched))
            if score_target is not target:
                contained_identity.append(enriched)
        elif score.decision is MatchDecision.REVIEW:
            review.append((score.total_score, enriched))

    accepted.sort(key=lambda item: item[0], reverse=True)
    review.sort(key=lambda item: item[0], reverse=True)
    if len(contained_identity) == 1:
        return RankedAppleCandidates(AppleCandidateDecision.AUTO, (contained_identity[0],), "query_contains_title_artist")
    if len(contained_identity) > 1:
        return RankedAppleCandidates(AppleCandidateDecision.PICKER, tuple(contained_identity), "ambiguous_versions")
    exact = [
        item
        for _score, item in accepted
        if _equivalent_text(target.title, item.get("name") or item.get("title"))
        and (not target.artist or _equivalent_text(target.artist, item.get("artist")))
    ]
    if len(exact) == 1:
        return RankedAppleCandidates(AppleCandidateDecision.AUTO, (exact[0],), "exact_title_artist")
    if len(exact) > 1:
        return RankedAppleCandidates(AppleCandidateDecision.PICKER, tuple(exact), "ambiguous_versions")
    if accepted:
        top_score = accepted[0][0]
        top = tuple(item for score, item in accepted if score == top_score)
        decision = AppleCandidateDecision.AUTO if len(top) == 1 and target.artist else AppleCandidateDecision.PICKER
        return RankedAppleCandidates(decision, top, "high_confidence")
    if review:
        return RankedAppleCandidates(AppleCandidateDecision.CONFIRM, (review[0][1],), "medium_confidence")
    return RankedAppleCandidates(AppleCandidateDecision.REJECT, (), "identity_mismatch")


def _equivalent_text(left: Any, right: Any) -> bool:
    left_variants = {
        normalize_music_text(value)
        for value in simplified_traditional_variants(str(left or ""))
    }
    right_variants = {
        normalize_music_text(value)
        for value in simplified_traditional_variants(str(right or ""))
    }
    return bool((left_variants - {""}) & (right_variants - {""}))


def _contains_equivalent(container: Any, value: Any) -> bool:
    needle_variants = {
        normalize_music_text(item)
        for item in simplified_traditional_variants(str(value or ""))
    } - {""}
    container_variants = {
        normalize_music_text(item)
        for item in simplified_traditional_variants(str(container or ""))
    } - {""}
    return bool(needle_variants and any(needle in haystack for needle in needle_variants for haystack in container_variants))

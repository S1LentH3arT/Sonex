"""Cross-language music identity matching for online audio candidates."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from src.log import sonex_home

LOGGER = logging.getLogger(__name__)

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
    "remaster",
    "remastered",
    "现场",
    "翻唱",
    "伴奏",
}
DISPLAY_SUFFIX_RE = re.compile(
    r"(?:\s+)?(?:official(?:\s+(?:audio|music\s+video|video|mv))?|lyrics?|lyric\s+video|"
    r"(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?)$",
    re.IGNORECASE,
)
SIMPLIFIED_TO_TRADITIONAL = str.maketrans({"丽": "麗", "来": "來"})
TRADITIONAL_TO_SIMPLIFIED = str.maketrans({"麗": "丽", "來": "来"})


class MatchDecision(StrEnum):
    ACCEPT = "accept"
    REVIEW = "review"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class CanonicalTrack:
    title: str
    artist: str
    album: str = ""
    duration_ms: int = 0
    provider: str = ""
    provider_id: str = ""
    isrc: str = ""
    musicbrainz_recording_id: str = ""
    spotify_track_id: str = ""
    preview_url: str = ""
    release_date: str = ""
    release_year: str = ""
    album_id: str = ""
    artist_id: str = ""
    provider_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LocalizedAlias:
    kind: str
    canonical: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AudioSearchResult:
    title: str
    artist: str
    provider: str
    album: str = ""
    duration_ms: int = 0
    provider_id: str = ""
    isrc: str = ""
    musicbrainz_recording_id: str = ""
    preview_url: str = ""
    release_date: str = ""
    release_year: str = ""
    album_id: str = ""
    artist_id: str = ""
    provider_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExpandedQuery:
    kind: str
    query: str
    strict: bool
    reason: str


@dataclass(frozen=True, slots=True)
class AliasMatch:
    kind: str
    left: str
    right: str
    canonical: str


@dataclass(frozen=True, slots=True)
class MatchScore:
    decision: MatchDecision
    total_score: int
    reasons: tuple[str, ...]
    hard_reject_reasons: tuple[str, ...]
    components: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision"] = self.decision.value
        data["reasons"] = list(self.reasons)
        data["hard_reject_reasons"] = list(self.hard_reject_reasons)
        return data


class AudioFingerprintVerifier(Protocol):
    @property
    def available(self) -> bool:
        ...

    def verify(self, audio_path: Path, track: CanonicalTrack) -> bool:
        ...


class FingerprintUnavailableVerifier:
    @property
    def available(self) -> bool:
        return False

    def verify(self, audio_path: Path, track: CanonicalTrack) -> bool:
        raise NotImplementedError("Audio fingerprint verification is not available in this dependency set.")


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


def _alias_key(value: Any) -> str:
    return normalize_music_text(value).translate(TRADITIONAL_TO_SIMPLIFIED)


class AliasResolver:
    def __init__(
        self,
        aliases: list[LocalizedAlias] | None = None,
        known_mismatches: list[dict[str, str]] | None = None,
    ) -> None:
        self.aliases = list(_builtin_aliases())
        if aliases:
            self.aliases.extend(aliases)
        self.known_mismatches = list(known_mismatches or [])
        self._groups: dict[str, dict[str, str]] = {}
        for alias in self.aliases:
            canonical_key = _alias_key(alias.canonical)
            for value in (alias.canonical, *alias.aliases):
                self._groups.setdefault(alias.kind, {})[_alias_key(value)] = canonical_key

    @classmethod
    def load(cls) -> "AliasResolver":
        path = sonex_home() / "music_aliases.json"
        if not path.exists():
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            LOGGER.warning("Ignoring invalid music aliases file: %s", type(exc).__name__)
            return cls()
        if not isinstance(payload, dict):
            LOGGER.warning("Ignoring invalid music aliases file: root must be an object.")
            return cls()

        aliases = _parse_aliases(payload.get("aliases"))
        mismatches = _parse_known_mismatches(payload.get("known_mismatches"))
        return cls(aliases=aliases, known_mismatches=mismatches)

    def matches(self, kind: str, left: Any, right: Any) -> bool:
        left_key = _alias_key(left)
        right_key = _alias_key(right)
        if not left_key or not right_key:
            return False
        if left_key == right_key:
            return True
        groups = self._groups.get(kind, {})
        return bool(groups.get(left_key) and groups.get(left_key) == groups.get(right_key))

    def aliases_for(self, kind: str, value: Any) -> list[str]:
        key = _alias_key(value)
        groups = self._groups.get(kind, {})
        canonical = groups.get(key, key)
        values: list[str] = []
        for alias in self.aliases:
            if alias.kind != kind:
                continue
            all_values = (alias.canonical, *alias.aliases)
            if any(groups.get(_alias_key(item), _alias_key(item)) == canonical for item in all_values):
                values.extend(all_values)
        seen: set[str] = set()
        ordered: list[str] = []
        for item in values or [str(value or "")]:
            if item and item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered

    def is_known_mismatch(self, track: CanonicalTrack, result: AudioSearchResult) -> bool:
        for mismatch in self.known_mismatches:
            if (
                self.matches("track", track.title, mismatch.get("title", ""))
                and self.matches("artist", track.artist, mismatch.get("artist", ""))
                and self.matches("track", result.title, mismatch.get("candidate_title", ""))
                and self.matches("artist", result.artist, mismatch.get("candidate_artist", ""))
            ):
                return True
        return False


def canonical_track_from_metadata(metadata: dict[str, Any] | None) -> CanonicalTrack:
    item = metadata if isinstance(metadata, dict) else {}
    return CanonicalTrack(
        title=_text(item.get("name") or item.get("title") or item.get("track")),
        artist=_joined_text(item.get("artist") or item.get("artists")),
        album=_text(item.get("album")),
        duration_ms=_int(item.get("duration_ms")),
        provider=_text(item.get("metadata_source") or item.get("provider")),
        provider_id=_text(item.get("id")),
        isrc=_text(item.get("isrc")),
        musicbrainz_recording_id=_text(item.get("musicbrainz_recording_id")),
        spotify_track_id=_text(item.get("spotify_track_id")),
        preview_url=_text(item.get("preview_url")),
        release_date=_text(item.get("release_date")),
        release_year=_text(item.get("release_year")),
        album_id=_text(item.get("album_id")),
        artist_id=_text(item.get("artist_id")),
        provider_payload=dict(item),
    )


def audio_result_from_candidate(candidate: dict[str, Any]) -> AudioSearchResult:
    return AudioSearchResult(
        title=_text(candidate.get("name") or candidate.get("title") or candidate.get("track")),
        artist=_joined_text(candidate.get("artist") or candidate.get("artists")),
        album=_text(candidate.get("album")),
        duration_ms=_int(candidate.get("duration_ms")),
        provider=_text(candidate.get("provider")),
        provider_id=_text(candidate.get("id")),
        isrc=_text(candidate.get("isrc")),
        musicbrainz_recording_id=_text(candidate.get("musicbrainz_recording_id")),
        preview_url=_text(candidate.get("preview_url")),
        release_date=_text(candidate.get("release_date")),
        release_year=_text(candidate.get("release_year")),
        album_id=_text(candidate.get("album_id")),
        artist_id=_text(candidate.get("artist_id")),
        provider_payload=dict(candidate),
    )


def expand_audio_queries(track: CanonicalTrack, resolver: AliasResolver | None = None) -> list[ExpandedQuery]:
    resolver = resolver or AliasResolver.load()
    queries: list[ExpandedQuery] = []
    for label, value in (("isrc", track.isrc), ("musicbrainz_recording_id", track.musicbrainz_recording_id)):
        if value:
            queries.append(ExpandedQuery("stable_id", f"{label}:{value}", True, label))

    def add(kind: str, query: str, strict: bool, reason: str) -> None:
        clean = " ".join(str(query or "").split())
        if clean and clean not in {item.query for item in queries}:
            queries.append(ExpandedQuery(kind, clean, strict, reason))

    add("metadata", f"{track.artist} {track.title} {track.album}", True, "title_artist_album")
    if track.duration_ms:
        add("metadata", f"{track.artist} {track.title} duration:{round(track.duration_ms / 1000)}", True, "title_artist_duration")
    for artist in resolver.aliases_for("artist", track.artist):
        for title in resolver.aliases_for("track", track.title):
            albums = resolver.aliases_for("album", track.album) if track.album else [""]
            for album in albums:
                add("alias", f"{artist} {title} {album}", True, "localized_alias")
    add("title_only", track.title, False, "loose_recall")
    return queries


def score_audio_match(
    track: CanonicalTrack,
    result: AudioSearchResult,
    resolver: AliasResolver | None = None,
) -> MatchScore:
    resolver = resolver or AliasResolver.load()
    reasons: list[str] = []
    hard_rejects: list[str] = []
    components: dict[str, int] = {}

    if _stable_id_match(track, result):
        score = MatchScore(MatchDecision.ACCEPT, 100, ("stable_id_match",), (), {"stable_id": 100})
        _log_match_decision(track, result, score)
        return score

    if resolver.is_known_mismatch(track, result):
        hard_rejects.append("known_mismatch")

    title_match = _title_matches(resolver, track.title, result.title)
    artist_match = resolver.matches("artist", _primary_artist(track.artist), _primary_artist(result.artist))
    album_match = bool(track.album and result.album and resolver.matches("album", track.album, result.album))

    if title_match:
        components["title"] = 45
        reasons.append("title_alias" if _alias_key(track.title) != _alias_key(result.title) else "title_exact")
    if artist_match:
        components["artist"] = 40
        reasons.append("artist_alias" if _alias_key(track.artist) != _alias_key(result.artist) else "artist_exact")
    elif track.artist and result.artist:
        hard_rejects.append("artist_mismatch")
    if album_match:
        components["album"] = 10
        reasons.append("album_alias" if _alias_key(track.album) != _alias_key(result.album) else "album_exact")

    duration_component, duration_reject = _duration_component(track.duration_ms, result.duration_ms)
    if duration_reject:
        hard_rejects.append("duration_conflict")
    elif duration_component:
        components["duration"] = duration_component
        reasons.append("duration_close")

    if _version_conflict(track.title, result.title):
        hard_rejects.append("version_conflict")

    if title_match and not artist_match:
        reasons.append("title_only_weak_evidence")

    if hard_rejects:
        score = MatchScore(MatchDecision.REJECT, sum(components.values()), tuple(reasons), tuple(sorted(set(hard_rejects))), components)
        _log_match_decision(track, result, score)
        return score

    total = sum(components.values())
    if title_match and artist_match and total >= 80:
        decision = MatchDecision.ACCEPT
    elif title_match or artist_match:
        decision = MatchDecision.REVIEW
    else:
        decision = MatchDecision.REJECT
        hard_rejects.append("insufficient_evidence")
    score = MatchScore(decision, total, tuple(reasons), tuple(hard_rejects), components)
    _log_match_decision(track, result, score)
    return score


def _builtin_aliases() -> list[LocalizedAlias]:
    return [
        LocalizedAlias("artist", "Khalil Fong", ("方大同",)),
        LocalizedAlias("track", "Beautiful", ("忘了美丽", "忘了美麗")),
        LocalizedAlias("album", "Wonderland", ("未来", "未來")),
    ]


def _log_match_decision(track: CanonicalTrack, result: AudioSearchResult, score: MatchScore) -> None:
    LOGGER.debug(
        "music_match decision=%s score=%s provider=%s source=%s target=%s reasons=%s hard_rejects=%s",
        score.decision.value,
        score.total_score,
        result.provider,
        {
            "title": normalize_music_text(result.title),
            "artist": normalize_music_text(result.artist),
            "album": normalize_music_text(result.album),
        },
        {
            "title": normalize_music_text(track.title),
            "artist": normalize_music_text(track.artist),
            "album": normalize_music_text(track.album),
        },
        list(score.reasons),
        list(score.hard_reject_reasons),
    )


def _parse_aliases(value: Any) -> list[LocalizedAlias]:
    aliases: list[LocalizedAlias] = []
    if not isinstance(value, dict):
        return aliases
    for kind, entries in value.items():
        if isinstance(entries, dict):
            for canonical, values in entries.items():
                if isinstance(values, list):
                    aliases.append(LocalizedAlias(str(kind), str(canonical), tuple(str(item) for item in values if item)))
        elif isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                canonical = _text(entry.get("canonical"))
                values = entry.get("aliases")
                if canonical and isinstance(values, list):
                    aliases.append(LocalizedAlias(str(kind), canonical, tuple(str(item) for item in values if item)))
    return aliases


def _parse_known_mismatches(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    required = {"title", "artist", "candidate_title", "candidate_artist"}
    parsed: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict) and required.issubset(item):
            parsed.append({key: str(item.get(key) or "") for key in required})
    return parsed


def _stable_id_match(track: CanonicalTrack, result: AudioSearchResult) -> bool:
    return bool(
        (track.isrc and result.isrc and normalize_music_text(track.isrc) == normalize_music_text(result.isrc))
        or (
            track.musicbrainz_recording_id
            and result.musicbrainz_recording_id
            and normalize_music_text(track.musicbrainz_recording_id) == normalize_music_text(result.musicbrainz_recording_id)
        )
    )


def _duration_component(source_ms: int, result_ms: int) -> tuple[int, bool]:
    if not source_ms or not result_ms:
        return 0, False
    diff = abs(source_ms - result_ms)
    if diff <= 5000:
        return 8, False
    if diff <= 15000:
        return 4, False
    longer = max(source_ms, result_ms)
    if diff > 30000 and diff / longer > 0.2:
        return 0, True
    return 0, False


def _version_conflict(source_title: str, result_title: str) -> bool:
    source = version_tags(source_title)
    result = version_tags(result_title)
    return bool(source != result and (source or result))


def _title_matches(resolver: AliasResolver, left: str, right: str) -> bool:
    return resolver.matches("track", left, right) or resolver.matches("track", _display_title(left), _display_title(right))


def _display_title(value: str) -> str:
    text = normalize_music_text(value)
    previous = None
    while text and text != previous:
        previous = text
        text = DISPLAY_SUFFIX_RE.sub("", text).strip()
    return text


def _primary_artist(value: str) -> str:
    return FEAT_RE.split(str(value or ""), maxsplit=1)[0].strip()


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _joined_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return _text(value)


def _int(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0

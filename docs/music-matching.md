# Music Matching

Sonex separates selected-track metadata from provider audio results. A selected
track can come from iTunes, Deezer, MusicBrainz, Spotify, or a user query, while
playable audio can come from Jamendo, Audius, or YouTube fallback. These systems
often localize names differently, so equality on normalized title and artist is
not enough.

## Canonical Model

`src/tools/music_matching.py` defines the matching boundary:

- `CanonicalTrack` represents the selected metadata identity.
- `AudioSearchResult` represents a normalized playable provider result.
- `ExpandedQuery` represents strict or loose searches derived from metadata.
- `MatchScore` carries `decision`, `total_score`, `reasons`,
  `hard_reject_reasons`, and component scores.
- `AudioFingerprintVerifier` is an interface only. The current dependency set
  has no fingerprint engine, so `FingerprintUnavailableVerifier` is explicit
  and raises when used.

Provider normalizers preserve stable fields when available: provider IDs, ISRC,
MusicBrainz recording IDs, preview URLs, duration, release date/year, album IDs,
artist IDs, and provider payloads.

## Built-In Aliases

The default resolver includes the cross-language identity needed for 方大同:

- artist: `Khalil Fong`, `方大同`
- track: `Beautiful`, `忘了美丽`, `忘了美麗`
- album: `Wonderland`, `未来`, `未來`

Text normalization uses NFKC, case folding, punctuation/spacing cleanup,
featured-artist normalization, display suffix stripping, and a lightweight
simplified/traditional Chinese variant map for the characters currently needed.

## User Alias File

Users can maintain additional aliases in:

```text
<sonex_home>/music_aliases.json
```

Example:

```json
{
  "aliases": {
    "artist": {
      "A-Lin": ["黄丽玲", "黃麗玲"]
    },
    "track": [
      {"canonical": "Romadiw", "aliases": ["如果可以"]}
    ]
  },
  "known_mismatches": [
    {
      "title": "Beautiful",
      "artist": "Khalil Fong",
      "candidate_title": "特别的人",
      "candidate_artist": "方大同"
    }
  ]
}
```

Invalid files are ignored with a sanitized warning. Audio URLs, token-bearing
query strings, and secrets are not logged.

## Decisions

`score_audio_match()` uses these rules:

- Stable ID matches such as ISRC or MusicBrainz recording ID are hard accepts.
- Known mismatches are hard rejects.
- Same title with a different non-aliased artist is a hard reject.
- Large duration conflicts are hard rejects.
- Incompatible versions such as live/remix/cover/karaoke are hard rejects unless
  both sides carry the same version evidence.
- Title-only evidence can never accept by itself. It returns `review` with
  `title_only_weak_evidence`.
- Alias-matched title and artist, optionally helped by album or duration, can
  accept.

`accept` candidates are eligible for automatic playback. `review` candidates can
be shown to the user with reasons, but they are not counted as auto-play
credible. `reject` candidates are filtered from playback results and remain
visible only in structured diagnostics.

Machine translation is intentionally weak evidence. It can help generate recall
queries in the future, but a translated string alone does not prove that two
provider records identify the same recording.

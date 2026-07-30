# Playback Selection Feedback Design

**Status:** Approved for implementation

**Date:** 2026-07-25

**Scope:** Normal-mode song-candidate playback and the `/player` backend picker

## Goal

Make a user's submitted playback choices visible in the chat transcript and
announce when the selected song has actually started playing.

The feedback must distinguish ordinary Agent messages from System-subject
messages without changing the WebSocket event family or the saved-session
schema.

## User-visible behavior

### Song candidate submission

Immediately after a valid song candidate is submitted, append one Agent message
with four physical lines:

```text
track: Sorry
artist: 方大同
album: 未来
source: iTunes
```

The message records the user's choice. It remains visible even if later audio
search or playback fails.

Field resolution is:

- `track`: candidate `name`, then `title`
- `artist`: candidate `artist`, then the first non-empty entry in `artists`
- `album`: candidate `album`
- `source`: candidate `provider`, then `metadata_source`, formatted through the
  existing metadata-provider display-name mapping

Every field must remain present. A missing or empty value renders as the em dash
`—`.

### Player submission inside the playback flow

If the song-candidate flow opens a player confirmation and the selected player
successfully starts playback, append this Agent message before the playing
announcement:

```text
player: mpv
```

Player names use the same display labels as the picker:

- `mpv` becomes `mpv`
- `cvlc` becomes `VLC`
- `auto` becomes `auto`

Cancellation, an expired confirmation, an invalid choice, or a failed player
launch does not append this message.

### `/player` system command

When a user invokes `/player` from the input box and successfully commits a
backend selection, append a System-subject message:

```text
player: VLC
```

This message does not imply that a song started and must not produce an
`on playing:` announcement. Cancellation, invalid selection, and tool failure
do not append the message.

### Successful song playback

After the song-candidate chain receives a successful playback result, append one
System-subject message:

```text
on playing: Sorry
```

The name resolves from successful result data when available, then from the
selected metadata candidate, with `—` as the final fallback.

This announcement applies only to the song-candidate chain. Local-file-only
playback, Spotify Mode, playlists, queues, recommendations, and unrelated
playback entry points are outside this change.

If playback succeeds without a player confirmation, the flow emits the candidate
Agent message and the System playing announcement, but no `player:` message.

## Message order

For a path that requires player confirmation:

```text
Agent:  track / artist / album / source
Agent:  player: <display name>
System: on playing: <track>
```

For a path that starts directly:

```text
Agent:  track / artist / album / source
System: on playing: <track>
```

Each successful playback result produces at most one `on playing:` message.

## Architecture

### Formatting helpers

Add small pure helpers near the existing playback and metadata formatting logic:

- format a selected metadata candidate into the four-line Agent message
- normalize a player backend into its picker display label
- format the single-line player and playing messages

The helpers coerce unexpected values safely and never raise on absent optional
metadata.

### Runtime emission points

Emit messages at the existing orchestration boundaries in `PlaySelectionSession`
and `PlayerBackendSelectionSession`:

1. After resolving a valid `song_candidate:<index>`, emit the candidate Agent
   message before audio resolution starts.
2. When a pending playback player confirmation returns success, emit the Agent
   player message, then emit the System playing message.
3. When song-candidate playback returns success without player confirmation,
   emit the System playing message.
4. When `/player` successfully invokes `local_playback_player`, emit the System
   player message.

Selection messages must not be inferred from frontend panel state. The backend
owns the authoritative candidate metadata, confirmation result, and playback
success state.

### System-subject transport

Extend the UI adapter with a focused System-message append path that sends the
existing chat payload shape:

```json
{
  "type": "chat",
  "role": "agent",
  "tone": "system",
  "text": "on playing: Sorry"
}
```

The frontend already maps `role: "agent"` plus `tone: "system"` to the purple
`System` subject. The adapter keeps the transcript entry in the existing
`agent`/`user` role schema, so no WebSocket event type, frontend chat role, or
session-save format changes are required.

## Failure and duplication rules

- A valid song selection message is retained even if later work fails.
- Player and playing messages are emitted only after a successful result.
- Cancellation, denial, invalid values, expired state, and failed tool results
  do not emit success feedback.
- Direct-success and post-confirmation success paths share one success-emission
  rule so one playback cannot emit duplicate `on playing:` messages.
- Feedback emission must not alter candidate selection, audio-source routing,
  cache updates, player invocation, Spotify behavior, or player state sync.

## Testing

Add focused regression coverage for:

- exact four-line candidate formatting
- provider display-name mapping and `—` missing-value placeholders
- candidate feedback occurring before playback work begins
- direct playback success producing candidate plus System playing feedback
- player-confirm success producing Agent player then System playing feedback
- `/player` success producing System player feedback
- cancellation, invalid selection, and playback failure producing no false
  player/playing messages
- System feedback using `type: "chat"`, `role: "agent"`, and `tone: "system"`
- unchanged transcript role schema

Run the normal verification gates:

```text
git diff --check
npm --prefix src/cli-ui test
npm --prefix src/cli-ui run build
SONEX_HOME=<fresh-directory> .venv/bin/python -m pytest -q
```

## Non-goals

- Changing candidate-panel visuals or candidate-row formatting
- Adding feedback to Spotify Mode, playlists, queues, or local-only playback
- Introducing a new WebSocket event type or a literal `system` chat role
- Changing saved-session data
- Refactoring unrelated playback or selector code

# Music Agent Playlists And Queue

## Goal

Add first-slice playlist persistence and queue browsing for the music agent while preserving the current playback/keymap work in the dirty `develop` workspace.

## Scope

- Add a focused playlist store module under `src/tools/playlists.py`.
- Add backend handling for `/playlist`, `/playlist save`, and `/queue`.
- Add CLI support for pseudo-fullscreen playlist and queue track panels below the header.
- Extend the playback keymap so `Ctrl+S` opens the playlist target picker.
- Add targeted Python and CLI tests for store behavior, command routing, panel events, and keymap mapping.

## Product Decisions

- `/queue` is a read-only recent-played 10-song view.
- Track lists are browse-only; Enter does not play.
- `Ctrl+S` opens a popup-style target playlist picker, defaulting to `likes`.
- Duplicate saves are strict no-ops.
- The mini-player `已收藏` indicator is deferred.

## Implementation Order

1. Add playlist persistence with protected `likes`, user playlist creation, strict dedupe, and track snapshots.
2. Add backend command parsing and execution for `/playlist`, `/playlist save`, and `/queue`.
3. Emit CLI events for playlist and queue panels.
4. Render pseudo-fullscreen playlist and queue track panels below the header.
5. Extend the existing playback keymap for `Ctrl+S`.
6. Run targeted Python and CLI verification.

## Verification

```bash
.venv/bin/python -m unittest tests.test_builtin_commands tests.test_builtin_command_runner tests.test_song_cache
npm --prefix src/cli-ui test
```

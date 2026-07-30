# Song Candidate Panel Visual Refresh Design

**Date:** 2026-07-25
**Status:** Approved for implementation planning

## Goal

Refresh only the ordinary-mode `song_candidate` confirmation panel so it uses
the same rounded, neutral frame language as the Mascot banner and presents
selection without a leading marker.

The result must preserve the existing candidate-row content contract:

- artist, album, title, and provider remain on one physical row;
- the row body remains 94 display columns;
- CJK display width remains supported;
- long titles keep the existing `...` truncation;
- provider text remains right-aligned with at least one separating space.

## Scope

The new presentation applies only when:

```text
confirm.tool_name === "song_candidate"
```

It does not change:

- Spotify track/device confirmation panels;
- playlist browsing;
- `/model`, `/lang`, `/help`, or other shared `ChoicePanel` consumers;
- confirmation keyboard behavior or `confirm_result` payloads;
- the Mascot or Mascot banner content;
- the WebSocket schema or session persistence.

## Visual Contract

### Frame

- Use Ink `borderStyle="round"`.
- Render a complete border rather than the current top-border-only treatment.
- Use neutral gray `#808791`.
- Remove the current vertical top padding so the title occupies the first
  interior row.
- Keep modest horizontal and bottom padding consistent with the input dock.

### Title and Hint

The first two interior rows are fixed and language-independent:

1. `Select the version to play`
2. `press Esc to cancel`

The title:

- uses the existing System subject color `CHAT_SYSTEM_MARKER_COLOR`
  (`#c8a6ff`);
- is bold;
- occupies the first row by itself.

The cancellation hint:

- uses the existing muted hint color `#7f5d6b`;
- occupies the second row by itself;
- is not merged with the title or a candidate row.

The backend `song_candidate` confirmation message is also changed to
`Select the version to play` so the event remains semantically correct before
frontend presentation. The frontend nevertheless keys the visual treatment
from `tool_name`, not from localized message text.

### Candidate Rows

For every row in the `song_candidate` panel:

- remove the selected `"> "` prefix;
- remove the unselected two-space placeholder prefix;
- render the formatted candidate label directly at the row start;
- do not add a selection background.

The selected row uses:

- foreground `BORDER_BLUE` (`#3b82f6`);
- `bold={true}` across the complete row.

Unselected rows keep the existing `#fff4f6` foreground and normal weight.
The fallback choice such as `没有想听的歌曲` follows the same marker-free
selection treatment even though it is not a structured music-candidate row.

## Component Design

`CompactConfirm` remains the owner of confirmation-panel framing. It derives an
`isSongCandidateConfirm` boolean from `confirm.tool_name`.

For this branch, `CompactConfirm`:

- renders the rounded gray frame;
- renders the fixed title and cancellation hint;
- maps the same visible choices into the existing shared `ChoicePanel`;
- passes song-candidate-specific presentation flags.

`ChoicePanel` remains shared. Add narrow presentation inputs for:

- whether to render a selection marker;
- whether the selected row is bold.

Defaults preserve all existing consumers. Only the `song_candidate` call site
disables the marker and enables selected-row bold styling. Spotify background
selection and every other selector retain their current behavior.

No new panel state or event type is introduced.

## Data and Interaction Flow

1. The Python selection session emits a `confirm` event with
   `tool_name="song_candidate"` and the fixed English message.
2. Existing localization leaves the fixed message unchanged in every language.
3. `App` stores the event in the existing confirmation state without schema
   changes.
4. `CompactConfirm` selects the song-candidate visual branch from
   `tool_name`.
5. Up/Down still changes `confirmIndex`; Enter and Esc retain the existing
   confirm/cancel behavior.
6. Only presentation changes when `confirmIndex` changes.

## Verification

Frontend source-contract tests must assert:

- the song-candidate branch is keyed by `tool_name`;
- the frame is round and gray;
- the title is fixed English, bold, and uses
  `CHAT_SYSTEM_MARKER_COLOR`;
- the hint is fixed English on its own row;
- `ChoicePanel` receives marker-disabled and selected-bold flags;
- candidate rows no longer render `"> "` for this branch;
- shared/default selector behavior remains intact.

Python tests must assert that generated `song_candidate` confirm events use:

```text
Select the version to play
```

Regression verification:

```bash
npm --prefix src/cli-ui test
npm --prefix src/cli-ui run build
.venv/bin/python -m pytest -q
git diff --check
```

Because the installed `sonex` command runs `src/cli-ui/dist`, rebuild the CLI
bundle before runtime inspection.

## Non-Goals

- No candidate content or ranking changes.
- No provider-label, truncation, or column-width changes.
- No generic redesign of `ChoicePanel`.
- No changes to Spotify green selection behavior.
- No changes to playlist or track-panel framing.
- No commit or push of implementation changes as part of this design-only
  step.

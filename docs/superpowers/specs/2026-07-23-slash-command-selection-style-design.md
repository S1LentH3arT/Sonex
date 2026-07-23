# Slash Command Selection Style Design

## Goal

Polish the slash-command suggestion panel opened by typing `/` so command rows
start at one shared left edge and the selected row uses a theme-colored bold
foreground without a background highlight.

## Scope

This change applies only to `SlashCommandList` in
`src/cli-ui/src/components.tsx`. It does not alter help panels, confirmation
pickers, playlist browsers, track panels, keyboard navigation, command
completion, command filtering, or command ordering.

## Rendering Contract

Every visible command row follows these rules:

- Render the command label at the panel's existing left inset, with no `>`
  marker and no compensating marker spaces.
- Preserve the existing fixed-width command column so descriptions remain
  aligned for both English and Chinese text.
- Keep unselected rows in the existing default foreground color and normal
  weight.
- In normal mode, render the entire selected row using `BORDER_BLUE` and bold
  weight.
- In Spotify mode, render the entire selected row using `SPOTIFY_GREEN` and
  bold weight.
- Do not set a background color for selected rows in either mode.
- Do not append background-filling spaces to a row.

The selected style covers the command label, its alignment padding, and the
description as one visual row.

## Component Design

`SlashCommandList` already receives `spotifyTheme` and computes the selected
row from `selectedIndex`. The implementation will keep that data flow and
change only the row presentation:

1. Derive the selected foreground from `spotifyTheme`.
2. Apply the foreground and `bold={selected}` to the selected row's `Text`.
3. Render the formatted command label and description without the marker
   segment or background-fill logic.

No new component, theme protocol, or state is needed.

## Interaction and Error Handling

Selection movement, Enter/Tab completion, and suggestion filtering remain
unchanged because the update does not touch `App.tsx` or command-matching
logic. The panel already returns `null` when there are no suggestions, so this
visual-only change introduces no new error path.

## Verification

Update the CLI UI source regression tests to assert that `SlashCommandList`:

- has no selected `>` marker;
- has no selected-row background color or fill;
- uses `BORDER_BLUE` in normal mode;
- uses `SPOTIFY_GREEN` in Spotify mode;
- applies bold styling only to the selected row;
- continues to render the fixed-width formatted command label.

Then run:

```text
git diff --check
npm --prefix src/cli-ui test
npm --prefix src/cli-ui run build
.venv/bin/python -m pytest -q
```

Because Sonex launches the compiled CLI UI, verify that the build refreshes
`src/cli-ui/dist` before evaluating the runtime appearance.

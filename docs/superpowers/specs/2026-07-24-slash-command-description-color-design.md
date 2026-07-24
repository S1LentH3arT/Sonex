# Slash Command Description Color Design

## Goal

Make unselected descriptions in the `/` command suggestion list visually secondary with the same neutral gray as the input border, while keeping selected commands emphasized in their active theme color.

## Root Cause

The description currently has a fixed nested `color="#9d7787"`. That value is pink-gray rather than the input border gray, and the nested override also prevents a selected description from inheriting the row's blue or Spotify green.

## Scope

- Update only `SlashCommandList` in `src/cli-ui/src/components.tsx`.
- Use input border gray `#808791` for unselected descriptions.
- Keep normal selected commands blue and bold.
- Keep Spotify Mode selected commands green and bold.
- Keep layout, truncation, navigation, and all other theming unchanged.
- Do not change the separate `/help` command panel.

## Rendering

Keep the existing row-level `commandColor` responsible for the selected theme color and retain `bold={selected}`. Derive `descriptionColor` from the same state:

- Selected: use `commandColor`, which is blue in normal mode and green in Spotify Mode.
- Unselected: use the input border gray `#808791`.

Apply `descriptionColor` only to the nested description `Text`. The command label continues to inherit the row color.

## Error Handling

No new runtime states or error paths are introduced. Existing behavior for an empty suggestion list and command-window bounds remains unchanged.

## Testing

Extend the focused source-level selector panel test to assert the state-derived description color and guard against a fixed pink-gray override. Existing assertions continue to protect the selected row's theme color and bold styling. Run the CLI UI test suite and production build, then run the Python test suite required by the repository commit workflow.

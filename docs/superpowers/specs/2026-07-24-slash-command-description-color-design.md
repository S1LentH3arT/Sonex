# Slash Command Description Color Design

## Goal

Make the description field in the `/` command suggestion list visually secondary by rendering it in the existing muted pink-gray `#9d7787`.

## Scope

- Update only `SlashCommandList` in `src/cli-ui/src/components.tsx`.
- Keep command labels, selected-row colors, bold styling, layout, truncation, navigation, and Spotify theming unchanged.
- Do not change the separate `/help` command panel.

## Rendering

Keep the row-level `Text` element responsible for selection color, bold styling, and truncation. Render the formatted command label in its existing nested `Text`, then render the description in a nested `Text` with `color="#9d7787"`. The nested color overrides the inherited row color only for the description.

## Error Handling

No new runtime states or error paths are introduced. Existing behavior for an empty suggestion list and command-window bounds remains unchanged.

## Testing

Extend the focused source-level selector panel test to assert that the slash-command description has the muted color. Run the CLI UI test suite and production build, then run the Python test suite required by the repository commit workflow.

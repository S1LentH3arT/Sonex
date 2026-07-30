# Slash Command Input Alignment Design

## Goal

Align the leading `/` of every slash-command suggestion with the `/` typed in
the input row directly below it.

## Cause

The non-minimal `InputDock` already wraps its panels in a container with
`paddingX={1}`. `SlashCommandList` adds another `paddingX={1}`, while the input
box uses only its own single `paddingX={1}`. The nested command-list padding
makes each suggestion start one character to the right of the input text.

## Scope

This change applies only to the horizontal layout of `SlashCommandList` in
`src/cli-ui/src/components.tsx`.

It does not change:

- normal-mode or Spotify-mode selection colors;
- selected-row bold styling;
- command label width or description alignment;
- suggestion filtering, ordering, scrolling, or keyboard behavior;
- help, confirmation, language, model, playlist, or track panels;
- the input box padding.

## Rendering Contract

- Keep the non-minimal `InputDock` panel wrapper at `paddingX={1}`.
- Remove the nested horizontal padding from the `SlashCommandList` column.
- Keep the input box at `paddingX={1}`.
- As a result, the first `/` of each suggestion and the first `/` typed in the
  input share the same terminal column.

No negative margin, compensating spaces, new layout property, state, or
component is required.

## Verification

Extend the existing `SlashCommandList` source regression coverage in
`src/cli-ui/test/selector-panel-source.test.ts` to assert:

- its root column is `<Box flexDirection="column">`;
- its source slice contains no `paddingX`;
- the surrounding `InputDock` panel wrapper still has `paddingX={1}`;
- the input box still has `paddingX={1}`;
- the existing theme-colored bold selection contract remains intact.

Then run:

```text
git diff --check
npm --prefix src/cli-ui test
npm --prefix src/cli-ui run build
.venv/bin/python -m pytest -q
```

Finally, rebuild the root workspace `src/cli-ui/dist` used by the installed
`sonex` command and confirm the compiled `SlashCommandList` has no horizontal
padding.

# Input Footer Model Status Design

## Status

Approved in conversation on 2026-07-25.

## Goal

Display the active LLM provider and model in the empty lower-left area beneath
the primary chat input using this format:

```text
[Provider] model-name
```

Examples:

```text
[OpenAI] gpt-5.5
[Anthropic] claude-sonnet-4-6
[Gemini] gemini-3.5-flash
```

The existing right-aligned green `🎧 Spotify Mode` marker remains unchanged.

## Requirements

### Functional

- Show the active provider and model on the left side of the current one-row
  input footer.
- Display normalized provider brand names for the five providers currently
  supported by Sonex:
  - `openai` -> `OpenAI`
  - `anthropic` -> `Anthropic`
  - `gemini` -> `Gemini`
  - `deepseek` -> `DeepSeek`
  - `ollama` -> `Ollama`
- Preserve the trimmed backend value for an unknown provider.
- Show model status only when authentication is ready and both provider and
  model are non-empty after trimming.
- Show no placeholder while authentication is unavailable, pending, or
  incomplete.
- Refresh the footer whenever a new `auth_state` event changes the current
  provider, model, or readiness.
- Use the same model-status behavior in ordinary and Spotify chat.
- Do not show model status while help, confirmation, setup, model selection, or
  another panel replaces the primary input.

### Visual

- Render model status in the existing input gray, `#808791`.
- Keep `🎧 Spotify Mode` bold and green.
- Preserve the footer at exactly one row; do not increase input-dock or
  conversation height.
- Give the model-status area the flexible width and the Spotify marker fixed
  width.
- On narrow terminals, truncate the model-status text at the end before
  allowing the Spotify marker to be clipped.
- When model status is hidden, keep the Spotify marker right-aligned exactly as
  it is today.

### Preserved Contracts

- Do not change input borders, prompt colors, cursor behavior, placeholders,
  or command hints.
- Do not change message rendering, chat flow, history behavior, or the
  three-row new-conversation reserve.
- Do not change Spotify styling outside the existing footer marker.
- Do not change the runtime information banner, WebSocket protocol, or session
  persistence.
- Do not modify the mascot or its spacing.

## Considered Approaches

### A. Pure formatter plus narrow presentation prop

Create a pure model-status formatter that accepts only the required
authentication fields and returns `string | null`. `App` computes the display
value from its current `authState`, then passes only `modelStatus` through the
conversation component chain to `InputDock`.

This is the selected approach. It isolates provider normalization and readiness
rules from Ink layout, makes the formatter easy to unit-test, and avoids
coupling every intermediate component to the full authentication state.

### B. Pass the complete authentication state to InputDock

Passing `AuthRuntimeState` through every component would require fewer
top-level expressions, but it would couple presentation components to
authentication fields they do not own. This approach is rejected.

### C. Derive model information from the runtime banner

The runtime banner is a historical chat item and can become stale after a model
change. Reading presentation state back from chat history would also reverse
the intended data flow. This approach is rejected.

## Architecture

### Pure formatter

Add `src/cli-ui/src/model-status.ts` with:

```ts
type ModelStatusInput = {
    ready: boolean;
    provider: string;
    model: string;
};

export const formatModelStatus = (
    input: ModelStatusInput,
): string | null;
```

The formatter will:

1. return `null` when `ready` is false;
2. trim `provider` and `model`;
3. return `null` if either trimmed value is empty;
4. normalize the provider case-insensitively through a fixed brand map;
5. retain the trimmed original provider when no map entry exists;
6. return `[${providerLabel}] ${model}`.

The formatter owns no Ink styling and has no dependency on the full
`AuthRuntimeState` type.

### App data source

`App` already owns the current `AuthRuntimeState` and replaces it whenever the
backend emits `auth_state`. It will import `formatModelStatus`, derive:

```ts
const modelStatus = formatModelStatus(authState);
```

and pass that value to `DynamicShell`.

No new React state or effect is required. The value updates as part of the
existing `authState` render.

### Component data flow

Add a required `modelStatus: string | null` presentation prop through:

```text
App
  -> DynamicShell
  -> ConversationRegion
  -> ConversationColumn
  -> InputDock
```

Mini-player and Spotify-immersive branches do not receive or render the prop.
The value reaches `InputDock` only through the normal conversation branch.

### Footer layout

Replace the footer's right-only alignment with an explicit two-region row:

```tsx
<Box height={1} paddingX={1} flexDirection="row">
    <Box flexGrow={1} minWidth={0}>
        {modelStatus ? (
            <Text color="#808791" wrap="truncate-end">{modelStatus}</Text>
        ) : null}
    </Box>
    {spotifyMode?.enabled ? (
        <Text bold color={SPOTIFY_GREEN}>{spotifyModeBorderLabel}</Text>
    ) : null}
</Box>
```

The left box always participates in layout even when it contains no text. This
keeps the Spotify marker right-aligned without rendering a model placeholder.
`flexGrow={1}` and `minWidth={0}` make the model area absorb narrow-terminal
pressure; `wrap="truncate-end"` keeps the footer to one physical row.

The footer remains inside the existing `showInput` branch, so panels that
replace the primary input also replace its model status.

## Data Flow

1. The WebSocket layer emits an `auth_state` event.
2. `App` updates `authState` through the existing event handler.
3. `formatModelStatus(authState)` returns a formatted string or `null`.
4. The value travels through the conversation presentation props.
5. `InputDock` renders it in the left footer region only while the primary
   input is visible.
6. Spotify mode independently controls the existing right footer marker.

No data is persisted and no backend request is added.

## Failure and Responsive Behavior

- `ready=false`: render no model status.
- Empty or whitespace-only provider: render no model status.
- Empty or whitespace-only model: render no model status.
- Unknown provider: use the trimmed original provider value.
- Provider casing differences: normalize through a lowercase lookup.
- Narrow terminal: truncate only the flexible model-status text; retain the
  fixed Spotify marker.
- Model change: the next `auth_state` render updates the footer without
  resetting input, focus, scroll offset, or conversation state.

## Testing

### Formatter unit tests

Add `src/cli-ui/test/model-status.test.ts` covering:

- all five supported provider brands;
- case-insensitive provider normalization;
- provider and model trimming;
- unknown-provider fallback;
- not-ready state;
- empty provider;
- empty model.

### Source contracts

Add a focused source-level test proving:

- `App` derives model status from the current `authState`;
- `DynamicShell`, `ConversationRegion`, `ConversationColumn`, and `InputDock`
  receive and forward `modelStatus`;
- the footer remains `height={1}`;
- the left region has `flexGrow={1}` and `minWidth={0}`;
- model text uses `#808791` and `wrap="truncate-end"`;
- the Spotify marker retains `bold` and `SPOTIFY_GREEN`;
- no placeholder such as `Unknown` or `-` is rendered by `InputDock`.

### Integrated verification

Run:

```bash
git diff --check
npm --prefix src/cli-ui test
npm --prefix src/cli-ui run build
.venv/bin/python -m pytest -q
```

Inspect the compiled `src/cli-ui/dist` because `scripts/sonex` launches that
runtime. Perform an 80-column PTY smoke check in both ordinary and Spotify
chat, then repeat at a narrow width to confirm the model text truncates while
the Spotify marker remains visible.

## Non-Goals

- Adding a model selector to the footer
- Making the footer clickable
- Localizing provider brand names
- Showing authentication method or credential source
- Showing model status outside the primary conversation input
- Changing the runtime banner or model-selection panel

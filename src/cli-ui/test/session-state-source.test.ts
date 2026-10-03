import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const eventSource = readFileSync(new URL('../src/event-coordination.ts', import.meta.url), 'utf8');

assert.match(typesSource, /\| \{ type: "session_state"; session_id: string \}/);
assert.match(typesSource, /\| \{ type: "usage_state"; input_tokens: number; output_tokens: number \}/);
assert.match(appSource, /const \{[\s\S]*sessionId,[\s\S]*tokenUsage,[\s\S]*\} = runtimeState/);
assert.match(appSource, /applyRuntimeEvent: \(event, raw\) => applyRuntimeAction\(\{ type: "event", event, rawEvent: raw \}\)/);
assert.match(eventSource, /bindings\.applyRuntimeEvent\(event, rawEvent\)/);
assert.match(
    appSource,
    /<HeaderFrame[\s\S]*?sessionId=\{sessionId\}/,
);
assert.match(appSource, /const modelStatus = formatModelStatus\(authState, displayedTokenUsage\);/);
assert.match(
    appSource,
    /setDisplayedTokenUsage\(\(current\) => nextAnimatedTokenUsage\(current, tokenUsage\)\)/,
);
assert.doesNotMatch(appSource, /<HeaderFrame[\s\S]*?tokenUsage=/);

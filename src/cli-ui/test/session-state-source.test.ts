import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

assert.match(typesSource, /\| \{ type: "session_state"; session_id: string \}/);
assert.match(typesSource, /\| \{ type: "usage_state"; input_tokens: number; output_tokens: number \}/);
assert.match(
    appSource,
    /const \[sessionId, setSessionId\] = useState<string \| null>\(null\)/,
);
assert.match(
    appSource,
    /case "session_state":[\s\S]*?sessionIdRef\.current = evt\.session_id;[\s\S]*?setSessionId\(evt\.session_id\);[\s\S]*?break;/,
);
assert.match(
    appSource,
    /<HeaderFrame[\s\S]*?sessionId=\{sessionId\}/,
);
assert.match(
    appSource,
    /case "usage_state":[\s\S]*?setTokenUsage\(\{[\s\S]*?inputTokens: evt\.input_tokens,[\s\S]*?outputTokens: evt\.output_tokens,[\s\S]*?\}\);[\s\S]*?break;/,
);
assert.match(appSource, /const modelStatus = formatModelStatus\(authState, displayedTokenUsage\);/);
assert.match(
    appSource,
    /setDisplayedTokenUsage\(\(current\) => nextAnimatedTokenUsage\(current, tokenUsage\)\)/,
);
assert.doesNotMatch(appSource, /<HeaderFrame[\s\S]*?tokenUsage=/);

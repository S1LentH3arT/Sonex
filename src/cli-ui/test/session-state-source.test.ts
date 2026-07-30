import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

assert.match(typesSource, /\| \{ type: "session_state"; session_id: string \}/);
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

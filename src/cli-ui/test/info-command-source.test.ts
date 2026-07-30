import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

assert.match(source, /const startupInfoCapturedRef = React\.useRef\(false\)/);
assert.match(source, /const RUNTIME_WORKING_DIRECTORY = process\.env\.SONEX_LAUNCH_CWD\?\.trim\(\) \|\| process\.cwd\(\);/);
assert.match(source, /case "auth_state":[\s\S]*!startupInfoCapturedRef\.current[\s\S]*commitItems\(\[createInfoBannerItem\(nextAuthState, RUNTIME_WORKING_DIRECTORY, sessionIdRef\.current\)\]\)/);
assert.match(source, /command\?\.name === "info"[\s\S]*setInput\(""\)[\s\S]*commitItems\(\[createInfoBannerItem\(authState, RUNTIME_WORKING_DIRECTORY, sessionIdRef\.current\)\]\)/);
assert.match(source, /<HeaderFrame[\s\S]*cwd=\{RUNTIME_WORKING_DIRECTORY\}/);
assert.match(source, /const transcriptItems = allTranscriptItems\(transcript\)/);
assert.match(source, /messages: chatMessagesForTranscript\(transcriptItems\)/);
assert.doesNotMatch(source, /type: "user_input", text: "\/info"/);

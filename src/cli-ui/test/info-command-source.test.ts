import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

assert.match(source, /const startupInfoCapturedRef = React\.useRef\(false\)/);
assert.match(source, /const RUNTIME_WORKING_DIRECTORY = process\.env\.SONEX_LAUNCH_CWD\?\.trim\(\) \|\| process\.cwd\(\);/);
assert.match(source, /case "auth_state":[\s\S]*!startupInfoCapturedRef\.current[\s\S]*createInfoBannerItem\([\s\S]*nextAuthState,[\s\S]*RUNTIME_WORKING_DIRECTORY,[\s\S]*sessionIdRef\.current,[\s\S]*\{ showLogo: true \},[\s\S]*\)/);
assert.match(source, /case "info":[\s\S]*setInput\(""\)[\s\S]*commitItems\(\[createInfoBannerItem\(authState, RUNTIME_WORKING_DIRECTORY, sessionIdRef\.current\)\]\)/);
assert.doesNotMatch(source, /tokenUsageRef/);
assert.match(source, /<HeaderFrame[\s\S]*cwd=\{RUNTIME_WORKING_DIRECTORY\}/);
assert.match(source, /const transcriptItems = allTranscriptItems\(transcript\)/);
assert.match(source, /messages: chatMessagesForTranscript\(transcriptItems\)/);
assert.doesNotMatch(source, /type: "user_input", text: "\/info"/);

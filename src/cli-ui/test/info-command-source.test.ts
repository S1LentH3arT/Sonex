import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

assert.match(source, /const startupInfoCapturedRef = React\.useRef\(false\)/);
assert.match(source, /case "auth_state":[\s\S]*!startupInfoCapturedRef\.current[\s\S]*createInfoBannerItem\(nextAuthState, process\.cwd\(\)\)/);
assert.match(source, /command\?\.name === "info"[\s\S]*setInput\(""\)[\s\S]*createInfoBannerItem\(authState, process\.cwd\(\)\)/);
assert.match(source, /messages: chatMessagesForTranscript\(chatItems\)/);
assert.doesNotMatch(source, /type: "user_input", text: "\/info"/);

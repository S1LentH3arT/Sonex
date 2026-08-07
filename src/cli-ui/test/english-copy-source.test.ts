import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const runnerSource = readFileSync(new URL('../../ws/runner.py', import.meta.url), 'utf8');
const websocketConstantsSource = readFileSync(new URL('../../ws/constants.py', import.meta.url), 'utf8');
const playerPermissionSource = readFileSync(new URL('../../tools/player_permission.py', import.meta.url), 'utf8');
const constantsSource = readFileSync(new URL('../src/constants.ts', import.meta.url), 'utf8');

const retiredVisibleCopy = [
    "选择播放后端",
    "没有想听的歌曲",
    "选择在线音源候选歌曲",
    "播放本地文件",
    "Successfully log out.",
    "Sonex wanna open",
    "Tips: try /random for a free play.",
];

const visibleSources = [
    runnerSource,
    websocketConstantsSource,
    playerPermissionSource,
    constantsSource,
].join("\n");

for (const text of retiredVisibleCopy) {
    assert.equal(visibleSources.includes(text), false, `retired visible copy remains: ${text}`);
}

assert.match(runnerSource, /"label": "Not found\? Type to supplement\."/);
assert.match(runnerSource, /"input": \{"placeholder": ""\}/);
assert.match(runnerSource, /"message": "Choose the default player"/);
assert.match(playerPermissionSource, /"confirm_message": f"Allow Sonex to open \{label\}\?"/);

// Multilingual setup triggers remain intentional and outside the display-copy audit.
assert.match(websocketConstantsSource, /"连接 spotify"/);

// Provider modes must not restore their retired natural-language direct routers.
assert.doesNotMatch(runnerSource, /def _handle_spotify_mode_input/);

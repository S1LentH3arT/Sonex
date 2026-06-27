import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');

assert.match(appSource, /const \[playbackKeymapEnabled, setPlaybackKeymapEnabled\] = useState\(true\)/);
assert.match(appSource, /process\.stdin\.on\("data", handlePlaybackShortcut\)/);
assert.match(appSource, /activeRegionRef\.current !== "miniPlayer"/);
assert.match(appSource, /!playbackSessionActiveRef\.current/);
assert.match(appSource, /!playbackKeymapEnabledRef\.current/);
assert.match(appSource, /confirmRef\.current/);
assert.match(appSource, /spotifySetupActiveRef\.current/);
assert.match(appSource, /authSetupActiveRef\.current/);
assert.match(appSource, /slashMenuActiveRef\.current/);
assert.match(appSource, /isLocalPlaybackShortcutSource\(playerRef\.current\)/);
assert.match(appSource, /send\(\{ type: "internal_command", text: command \}\)/);
assert.match(appSource, /case "track_panel":/);
assert.match(appSource, /setTrackPanel\(\{/);
assert.match(appSource, /const selectedTrackPanelTrack = trackPanel\.tracks\[Math\.min\(trackPanelIndex, Math\.max\(0, trackPanel\.tracks\.length - 1\)\)\] \?\? null;/);
assert.match(appSource, /const isTrackPanelQueueShortcut = \(inputKey: string, key: .*?\): boolean =>/);
assert.match(appSource, /return Boolean\(key\.ctrl && \(inputKey === "\\x01" \|\| inputKey\.toLowerCase\(\) === "a"\)\);/);
assert.match(appSource, /isTrackPanelQueueShortcut\(inputKey, key\) && selectedTrackPanelTrack/);
assert.match(appSource, /send\(\{ type: "track_panel_action", action: "queue_add", track: selectedTrackPanelTrack, panel: trackPanel\.panel, title: trackPanel\.title \}\)/);
assert.match(appSource, /send\(\{ type: "track_panel_action", action: "play", track: selectedTrackPanelTrack, panel: trackPanel\.panel, title: trackPanel\.title \}\)/);
assert.match(
    appSource,
    /key\.return && selectedTrackPanelTrack\) \{\s*setTrackPanel\(null\);\s*setTrackPanelIndex\(0\);\s*switchRegion\("chat"\);\s*send\(\{ type: "track_panel_action", action: "play", track: selectedTrackPanelTrack, panel: trackPanel\.panel, title: trackPanel\.title \}\);/,
);
assert.match(typesSource, /type: "track_panel"/);
assert.match(typesSource, /panel: "queue" \| "playlist"/);
assert.match(typesSource, /type: "track_panel_action"; action: "queue_add" \| "play"; track: TrackPanelTrack; panel: "queue" \| "playlist"; title: string/);

const chatScrollInput = appSource.match(/useInput\(\(inputKey, key\) => \{[\s\S]*?scrollChat\(-1\);[\s\S]*?\}, \{ isActive: ([\s\S]*?) \}\);/);
assert.ok(chatScrollInput);
assert.match(chatScrollInput[1] ?? "", /activeRegion !== "miniPlayer"/);

assert.match(typesSource, /type: "internal_command"; text: string/);

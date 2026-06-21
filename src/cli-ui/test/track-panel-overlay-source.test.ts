import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentsSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.doesNotMatch(componentsSource, /Conversation<\/Text>/);
assert.match(componentsSource, /trackPanel\.queue/);
assert.match(componentsSource, /trackPanel\.playlist/);
assert.match(componentsSource, /localizeTrackPanelTitle\(panel, language\)/);
assert.match(componentsSource, /const rows: TrackPanelTrack\[\] = panel\.tracks\.slice\(0, 10\);/);
assert.doesNotMatch(componentsSource, /Array\.from\(\{ length: 10 \}/);
assert.match(componentsSource, /const TrackPanelOverlay = \(\{ trackPanel, language = "en" \}: \{ trackPanel: TrackPanelState; language\?: UiLanguage \}\) =>/);
assert.match(componentsSource, /<TrackPanelOverlay trackPanel=\{trackPanel\} language=\{language\} \/>/);
assert.doesNotMatch(componentsSource, /<TrackPanel panel=\{trackPanel\} \/>/);
assert.match(appSource, /case "queue":[\s\S]*setQueueItems\(evt\.tracks\);/);
assert.match(
    appSource,
    /case "queue":[\s\S]*setTrackPanel\(\(current\) => current && current\.panel === "queue" \? \{ \.\.\.current, tracks: evt\.tracks \} : current\);/,
);
assert.match(appSource, /if \(key\.escape\) \{\s*setTrackPanel\(null\);/);

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentsSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.doesNotMatch(componentsSource, /Conversation<\/Text>/);
assert.match(componentsSource, /const TrackPanelOverlay = \(\{ trackPanel \}: \{ trackPanel: TrackPanelState \}\) =>/);
assert.match(componentsSource, /<TrackPanelOverlay trackPanel=\{trackPanel\} \/>/);
assert.doesNotMatch(componentsSource, /<TrackPanel panel=\{trackPanel\} \/>/);
assert.match(appSource, /case "queue":[\s\S]*setQueueItems\(evt\.tracks\);/);
assert.match(
    appSource,
    /case "queue":[\s\S]*setTrackPanel\(\(current\) => current && current\.panel === "queue" \? \{ \.\.\.current, tracks: evt\.tracks \} : current\);/,
);
assert.match(appSource, /if \(key\.escape\) \{\s*setTrackPanel\(null\);/);

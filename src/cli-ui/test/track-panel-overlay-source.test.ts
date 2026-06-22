import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentsSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.doesNotMatch(componentsSource, /Conversation<\/Text>/);
assert.match(componentsSource, /trackPanel\.queue/);
assert.match(componentsSource, /trackPanel\.playlist/);
assert.match(componentsSource, /localizeTrackPanelTitle\(panel, language\)/);
assert.match(componentsSource, /const SPOTIFY_TRACK_ARTIST_WIDTH = 16/);
assert.match(componentsSource, /const SPOTIFY_TRACK_INDEX_WIDTH = 3/);
assert.match(componentsSource, /const isSpotifyTrackPanel = \(panel: NonNullable<TrackPanelState>\): boolean =>/);
assert.match(componentsSource, /const formatSpotifyTrackPanelIndex = \(track: TrackPanelTrack\): string =>/);
assert.match(componentsSource, /padDisplayWidth\(track\.index, SPOTIFY_TRACK_INDEX_WIDTH\)/);
assert.match(componentsSource, /padDisplayWidth\(track\.artist, SPOTIFY_TRACK_ARTIST_WIDTH\)/);
assert.match(componentsSource, /borderColor=\{spotifyPanel \? SPOTIFY_GREEN : BORDER_BLUE\}/);
assert.match(componentsSource, /const fillTrackPanelLine = \(value: string\): string =>/);
assert.match(componentsSource, /const spotifyIndex = formatSpotifyTrackPanelIndex\(track\);/);
assert.match(componentsSource, /const selectedSpotifyLine = selectedBackground \? fillTrackPanelLine\(`>> \$\{spotifyIndex\} \$\{title\}`\) : null;/);
assert.match(componentsSource, /<Text color=\{SPOTIFY_SELECTED_TEXT\} backgroundColor=\{SPOTIFY_GREEN\} wrap="truncate-end">\{selectedSpotifyLine\}<\/Text>/);
assert.match(componentsSource, /width="100%" flexDirection="column" marginBottom=\{1\}/);
assert.match(componentsSource, /selectedIndex = 0/);
assert.match(componentsSource, /visibleCommandWindow\(\s*panel\.tracks,\s*selectedIndex,\s*10,\s*\)/);
assert.doesNotMatch(componentsSource, /panel\.tracks\.slice\(0, 10\)/);
assert.doesNotMatch(componentsSource, /Array\.from\(\{ length: 10 \}/);
assert.match(componentsSource, /panel\.panel === "queue" \? track\.duration : null/);
assert.doesNotMatch(componentsSource, /`\$\{track\.artist\} • \$\{track\.duration\}`/);
assert.match(componentsSource, /const TrackPanelOverlay = \(\{ trackPanel, selectedIndex = 0, language = "en" \}/);
assert.match(componentsSource, /<TrackPanelOverlay trackPanel=\{trackPanel\} selectedIndex=\{trackPanelIndex\} language=\{language\} \/>/);
assert.doesNotMatch(componentsSource, /<TrackPanel panel=\{trackPanel\} \/>/);
assert.match(appSource, /const \[trackPanelIndex, setTrackPanelIndex\] = useState\(0\);/);
assert.match(appSource, /setTrackPanelIndex\(0\);/);
assert.match(appSource, /case "queue":[\s\S]*setQueueItems\(evt\.tracks\);/);
assert.match(
    appSource,
    /case "queue":[\s\S]*setTrackPanel\(\(current\) => current && current\.panel === "queue" \? \{ \.\.\.current, tracks: evt\.tracks \} : current\);/,
);
assert.match(appSource, /key\.upArrow[\s\S]*setTrackPanelIndex\(\(prev\) => Math\.max\(0, prev - 1\)\);/);
assert.match(appSource, /key\.downArrow[\s\S]*setTrackPanelIndex\(\(prev\) => Math\.min\(trackPanel\.tracks\.length - 1, prev \+ 1\)\);/);
assert.match(appSource, /if \(key\.escape\) \{\s*setTrackPanel\(null\);/);

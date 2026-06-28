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
assert.match(componentsSource, /const TRACK_PANEL_MIN_VISIBLE_ROWS = 4/);
assert.match(componentsSource, /const isPlaylistTrackPanel = \(panel: NonNullable<TrackPanelState>\): boolean =>/);
assert.match(componentsSource, /const formatSpotifyTrackPanelIndex = \(track: TrackPanelTrack\): string =>/);
assert.match(componentsSource, /padStartDisplayWidth\(track\.index, SPOTIFY_TRACK_INDEX_WIDTH\)/);
assert.match(componentsSource, /track\.queued \? `✓\$\{index\}` : ` \$\{index\}`/);
assert.match(componentsSource, /padDisplayWidth\(track\.artist, SPOTIFY_TRACK_ARTIST_WIDTH\)/);
assert.match(componentsSource, /borderColor=\{isSpotifyThemePanel \? SPOTIFY_GREEN : BORDER_BLUE\}/);
assert.match(componentsSource, /const spotifyIndex = formatSpotifyTrackPanelIndex\(track\);/);
assert.match(componentsSource, /const spotifyLine = `\$\{spotifyIndex\} \$\{title\}`;/);
assert.match(componentsSource, /const rowBackgroundColor = selected \? \(isSpotifyThemePanel \? SPOTIFY_GREEN : "#4b2f3a"\) : undefined;/);
assert.match(componentsSource, /const rowFill = rowBackgroundColor \? " "\.repeat\(Math\.max\(0, 96 - stringWidth\(/);
assert.match(componentsSource, /<Text backgroundColor=\{rowBackgroundColor\} wrap="truncate-end">/);
assert.match(componentsSource, /const rowColor = selectedBackground[\s\S]*: "#fff4f6";/);
assert.match(componentsSource, /<Text bold color=\{isSpotifyThemePanel \? SPOTIFY_GREEN : "#f3b2c6"\}>/);
assert.doesNotMatch(componentsSource, /width="100%" flexDirection="column" marginBottom=\{1\}/);
assert.doesNotMatch(componentsSource, /<Box marginBottom=\{1\}>\s*<Text bold color=\{isSpotifyThemePanel \? SPOTIFY_GREEN : "#f3b2c6"\}>\{panelTitle\}<\/Text>/);
assert.doesNotMatch(componentsSource, /<Box flexDirection="column" flexGrow=\{1\} flexShrink=\{1\} minHeight=\{0\} paddingTop=\{1\}>/);
assert.doesNotMatch(componentsSource, /"\.\."/);
assert.doesNotMatch(componentsSource, /`>> \$\{spotifyIndex\}/);
assert.match(componentsSource, /selectedIndex = 0/);
assert.match(componentsSource, /visibleCommandWindow\(\s*panel\.tracks,\s*selectedIndex,\s*availableRows,\s*\)/);
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
    /case "queue":[\s\S]*setTrackPanel\(\(current\) => current \? \{ \.\.\.current, tracks: markQueuedTracks\(current\.panel === "queue" \? evt\.tracks : current\.tracks, evt\.tracks\) \} : current\);/,
);
assert.match(appSource, /case "track_panel":[\s\S]*tracks: markQueuedTracks\(evt\.tracks, queueItems\),/);
assert.match(appSource, /key\.upArrow[\s\S]*setTrackPanelIndex\(\(prev\) => Math\.max\(0, prev - 1\)\);/);
assert.match(appSource, /key\.downArrow[\s\S]*setTrackPanelIndex\(\(prev\) => Math\.min\(trackPanel\.tracks\.length - 1, prev \+ 1\)\);/);
assert.match(appSource, /if \(key\.escape\) \{\s*setTrackPanel\(null\);/);

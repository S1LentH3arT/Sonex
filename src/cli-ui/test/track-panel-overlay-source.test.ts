import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentsSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const trackPanelStart = componentsSource.indexOf('const TrackPanel =');
const trackPanelOverlayStart = componentsSource.indexOf('const TrackPanelOverlay =');
const coverAtmosphereStart = componentsSource.indexOf('const CoverAtmosphere =');
const dynamicShellStart = componentsSource.indexOf('export const DynamicShell =');

assert.ok(trackPanelStart >= 0);
assert.ok(trackPanelOverlayStart > trackPanelStart);
assert.ok(coverAtmosphereStart > trackPanelOverlayStart);
assert.ok(dynamicShellStart > coverAtmosphereStart);

const trackPanelBody = componentsSource.slice(trackPanelStart, trackPanelOverlayStart);
const trackPanelOverlayBody = componentsSource.slice(trackPanelOverlayStart, coverAtmosphereStart);
const dynamicShellBody = componentsSource.slice(dynamicShellStart);

assert.doesNotMatch(componentsSource, /Conversation<\/Text>/);
assert.match(componentsSource, /trackPanel\.queue/);
assert.match(componentsSource, /trackPanel\.playlist/);
assert.match(componentsSource, /localizeTrackPanelTitle\(panel, language\)/);
assert.match(componentsSource, /const TRACK_PANEL_MIN_VISIBLE_ROWS = 4/);
assert.match(componentsSource, /formatTrackPanelLine\(track, TRACK_PANEL_ROW_WIDTH\)/);
assert.doesNotMatch(componentsSource, /const SPOTIFY_TRACK_ARTIST_WIDTH|const SPOTIFY_TRACK_INDEX_WIDTH/);
assert.doesNotMatch(componentsSource, /panel\.tracks\.slice\(0, 10\)|Array\.from\(\{ length: 10 \}/);

// Track panels use the same shared frame and selection-list primitives.
assert.match(
    trackPanelBody,
    /panelWidth,[\s\S]*spotifyTheme = false,[\s\S]*panelWidth: number;[\s\S]*spotifyTheme\?: boolean/,
);
assert.match(
    trackPanelBody,
    /<PanelFrame[\s\S]*width=\{panelWidth\}[\s\S]*paddingX=\{2\}[\s\S]*title=\{panelTitle\}[\s\S]*hint=\{panel\.hint \? `\$\{panel\.hint\}; Esc to hide` : null\}/,
);
assert.match(trackPanelBody, /const items: PanelChoiceItem\[\] = panel\.tracks\.map/);
assert.match(trackPanelBody, /text: formatTrackPanelLine\(track, TRACK_PANEL_ROW_WIDTH\)/);
assert.match(
    trackPanelBody,
    /<PanelChoiceList[\s\S]*items=\{items\}[\s\S]*selectedIndex=\{selectedIndex\}[\s\S]*visibleLimit=\{availableRows\}[\s\S]*width=\{panelWidth\}[\s\S]*paddingX=\{2\}[\s\S]*spotifyTheme=\{spotifyTheme\}/,
);
assert.match(trackPanelBody, /<PanelEmptyRow key=\{`track-panel-filler-\$\{index\}`\} width=\{panelWidth\} \/>/);
assert.doesNotMatch(
    trackPanelBody,
    /borderStyle=|borderColor=|selectedBackground|rowBackgroundColor|backgroundColor=\{row|isSpotifyThemePanel|`>>|selected \? "> "/,
);

assert.match(
    trackPanelOverlayBody,
    /trackPanel,[\s\S]*panelWidth,[\s\S]*spotifyTheme = false/,
);
assert.match(
    trackPanelOverlayBody,
    /<TrackPanel[\s\S]*panel=\{trackPanel\}[\s\S]*panelWidth=\{panelWidth\}[\s\S]*expanded=\{true\}[\s\S]*selectedIndex=\{selectedIndex\}[\s\S]*spotifyTheme=\{spotifyTheme\}/,
);

// The selected color comes from the actual active Spotify provider mode.
assert.match(dynamicShellBody, /if \(activeRegion === "trackPanel" && trackPanel\)/);
assert.match(
    dynamicShellBody,
    /<TrackPanelOverlay[\s\S]*trackPanel=\{trackPanel\}[\s\S]*selectedIndex=\{trackPanelIndex\}[\s\S]*panelWidth=\{Math\.max\(3, Math\.floor\(terminalSpace\.columns \?\? 80\)\)\}[\s\S]*spotifyTheme=\{spotifyMode\.enabled\}[\s\S]*language=\{language\}/,
);
assert.doesNotMatch(dynamicShellBody, /isSpotifyThemePanel/);

// Track-panel state and keyboard behavior are deliberately unchanged.
assert.match(appSource, /const \[trackPanelIndex, setTrackPanelIndex\] = useState\(0\)/);
assert.match(appSource, /setTrackPanelIndex\(0\)/);
assert.match(appSource, /case "queue":[\s\S]*setQueueItems\(evt\.tracks\)/);
assert.match(
    appSource,
    /case "queue":[\s\S]*setTrackPanel\(\(current\) => current \? \{ \.\.\.current, tracks: markQueuedTracks\(current\.panel === "queue" \? evt\.tracks : current\.tracks, evt\.tracks\) \} : current\)/,
);
assert.match(appSource, /case "track_panel":[\s\S]*tracks: markQueuedTracks\(evt\.tracks, queueItems\)/);
assert.match(appSource, /case "track_panel":[\s\S]*switchRegion\("trackPanel"\)/);
assert.match(appSource, /key\.upArrow[\s\S]*setTrackPanelIndex\(\(prev\) => Math\.max\(0, prev - 1\)\)/);
assert.match(appSource, /key\.downArrow[\s\S]*setTrackPanelIndex\(\(prev\) => Math\.min\(trackPanel\.tracks\.length - 1, prev \+ 1\)\)/);
assert.match(appSource, /if \(key\.escape\) \{\s*setTrackPanel\(null\)/);
assert.match(appSource, /isActive: activeRegion === "trackPanel"/);

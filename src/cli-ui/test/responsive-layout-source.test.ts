import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const spotifyImmersiveSource = componentSource.slice(
    componentSource.indexOf('const SpotifyImmersiveRegion ='),
    componentSource.indexOf('const ConversationRegion ='),
);

assert.equal(appSource.includes('<Static items={bannerItems}>'), false);
assert.match(appSource, /resolveChatHeaderVariant/);
assert.match(appSource, /usePlaybackProgressWriter/);
assert.match(appSource, /resolveSpotifyImmersiveLayout/);
assert.match(appSource, /const spotifyImmersiveLayout = React\.useMemo/);
assert.match(appSource, /enabled: miniVisible \|\| spotifyImmersiveVisible/);
assert.match(appSource, /position: spotifyImmersiveVisible \? spotifyImmersiveLayout\.progressSlot : miniLayout\.progressSlot/);
assert.equal(appSource.includes('useMiniProgressWriter'), false);
assert.match(appSource, /setTimeout\([\s\S]*80/);
assert.match(appSource, /clearTerminalForLayoutSwitch\(stdout\);[\s\S]*setMiniSnapshotRevision/);
assert.match(appSource, /spotifyModeEnabled: spotifyModeRef\.current\.enabled/);
assert.match(appSource, /toggleShellRegion\(activeRegionRef\.current, playbackSessionActiveRef\.current, spotifyModeRef\.current\.enabled\)/);
assert.match(appSource, /activeRegionRef\.current === "spotifyImmersive"[\s\S]*switchRegion\("chat"\);[\s\S]*return;/);
assert.match(appSource, /activeRegion !== "miniPlayer" && activeRegion !== "spotifyImmersive"/);
assert.match(appSource, /activeRegion === "chat" \? <HeaderFrame/);
assert.equal(appSource.includes('terminalSize.rows - 8'), false);
assert.equal(appSource.includes('terminalSize.columns - 4'), false);

assert.match(componentSource, /resolveMiniPlayerLayout/);
assert.match(componentSource, /wrap="truncate-end"/);
assert.match(componentSource, /measureElement\(containerRef\.current\)/);
assert.match(componentSource, /width[^\n]*height/);
assert.match(componentSource, /const SpotifyImmersiveRegion =/);
assert.match(componentSource, /spotifyMode\.device_name \?\? "Spotify Connect"/);
assert.match(componentSource, /spotifyImmersiveLayout: SpotifyImmersiveLayout/);
assert.match(spotifyImmersiveSource, /spotifyImmersiveLayout\.deviceSlot\.width/);
assert.match(spotifyImmersiveSource, /<Box height=\{1\} marginTop=\{1\} \/>/);
assert.match(spotifyImmersiveSource, /<Box width=\{deviceWidth > 0 \? deviceWidth : undefined\} justifyContent="center">/);
assert.equal(spotifyImmersiveSource.includes('const progress = buildPlaybackProgressLine(player'), false);
assert.equal(spotifyImmersiveSource.includes('{progress}</Text>'), false);
assert.equal(spotifyImmersiveSource.includes('{formatDuration(progressMs)} / {formatDuration(player.duration_ms)}'), false);
assert.match(componentSource, /activeRegion === "spotifyImmersive"/);
assert.match(componentSource, /<SpotifyImmersiveRegion[\s\S]*spotifyMode=\{spotifyMode\}[\s\S]*spotifyImmersiveLayout=\{spotifyImmersiveLayout\}/);
assert.equal(componentSource.includes('<MiniPlaybackMeter'), false);

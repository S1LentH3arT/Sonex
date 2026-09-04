import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const spotifyImmersiveSource = componentSource.slice(
    componentSource.indexOf('const ProviderImmersiveRegion ='),
    componentSource.indexOf('export const DynamicShell ='),
);
const committedTranscriptSource = componentSource.slice(
    componentSource.indexOf('export const CommittedTranscript ='),
    componentSource.indexOf('const localizeTrackPanelTitle'),
);
const dynamicTailSource = componentSource.slice(
    componentSource.indexOf('export const DynamicTail ='),
    componentSource.indexOf('function useVisibleSnapshotOnRevision'),
);
const dynamicShellSource = componentSource.slice(
    componentSource.indexOf('export const DynamicShell ='),
);

assert.equal(appSource.includes('<Static items={bannerItems}>'), false);
assert.match(appSource, /resolveChatHeaderVariant/);
assert.match(appSource, /usePlaybackProgressWriter/);
assert.match(appSource, /resolveSpotifyImmersiveLayout/);
assert.match(appSource, /const spotifyImmersiveLayout = React\.useMemo/);
assert.match(appSource, /enabled: stdout\.isTTY === true && \(miniVisible \|\| spotifyImmersiveVisible\)/);
assert.match(appSource, /position: spotifyImmersiveVisible \? spotifyImmersiveLayout\.progressSlot : miniLayout\.progressSlot/);
assert.equal(appSource.includes('useMiniProgressWriter'), false);
assert.match(appSource, /providerMode: providerModeRef\.current\.enabled/);
assert.match(appSource, /providerModeRef\.current\.enabled/);
assert.match(appSource, /if \(key\.tab \|\| inputKey === "\\t"\) \{[\s\S]*type: "toggle_region"/);
assert.equal(appSource.includes('if (shellStateRef.current.region === "spotifyImmersive")'), false);
assert.doesNotMatch(appSource, /activeRegion === "chat" \? <HeaderFrame/);
assert.match(appSource, /const showFixedHeader = activeRegion === "chat" && authInterfaceActive/);
assert.match(appSource, /\{showFixedHeader \? \([\s\S]*<HeaderFrame[\s\S]*authState=\{authState\}/);
assert.equal(appSource.includes('terminalSize.rows - 8'), false);
assert.equal(appSource.includes('terminalSize.columns - 4'), false);

assert.match(componentSource, /resolveMiniPlayerLayout/);
assert.match(componentSource, /wrap="truncate-end"/);
assert.match(componentSource, /width[^\n]*height/);
assert.match(componentSource, /const ProviderImmersiveRegion =/);
assert.match(componentSource, /spotifyMode\.device_name \?\? "Spotify Connect"/);
assert.match(spotifyImmersiveSource, /const deviceStatus = player\.is_playing \? "playing" : "paused"/);
assert.match(spotifyImmersiveSource, /`\$\{deviceStatus\} on \$\{deviceName\}`/);
assert.match(componentSource, /spotifyImmersiveLayout: SpotifyImmersiveLayout/);
assert.match(spotifyImmersiveSource, /spotifyImmersiveLayout\.deviceSlot\.width/);
assert.match(spotifyImmersiveSource, /<Box height=\{1\} marginTop=\{1\} \/>/);
assert.match(spotifyImmersiveSource, /<Box width=\{deviceWidth > 0 \? deviceWidth : undefined\} justifyContent="center">/);
assert.equal(spotifyImmersiveSource.includes('const progress = buildPlaybackProgressLine(player'), false);
assert.equal(spotifyImmersiveSource.includes('{progress}</Text>'), false);
assert.equal(spotifyImmersiveSource.includes('{formatDuration(progressMs)} / {formatDuration(player.duration_ms)}'), false);
assert.match(componentSource, /activeRegion === "spotifyImmersive"/);
assert.match(componentSource, /<ProviderImmersiveRegion[\s\S]*spotifyMode=\{spotifyMode\}[\s\S]*providerMode=\{providerMode\}[\s\S]*spotifyImmersiveLayout=\{spotifyImmersiveLayout\}/);
assert.equal(componentSource.includes('<MiniPlaybackMeter'), false);
assert.match(committedTranscriptSource, /<Static items=\{records\}>/);
assert.match(committedTranscriptSource, /<CommittedRecord[\s\S]*key=\{record\.sequence\}/);
assert.match(dynamicTailSource, /<MiniMascotStatus/);
assert.match(dynamicTailSource, /<InputDock/);
assert.match(dynamicShellSource, /activeRegion === "trackPanel"/);
assert.match(dynamicShellSource, /<DynamicTail/);
assert.doesNotMatch(
    componentSource,
    /ChatPane|ConversationColumn|ConversationRegion|resolveConversationFlow|getChatContentRows|viewportRows|chatScrollOffset/,
);

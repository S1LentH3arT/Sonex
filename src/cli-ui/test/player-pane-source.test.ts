import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.match(source, /const MiniPlayerStaticBody = React\.memo/);
assert.match(source, /const MiniPlayerRegion =/);
assert.match(source, /const ConversationRegion =/);
assert.match(source, /const miniSnapshot = useVisibleSnapshotOnRevision/);
assert.match(source, /<PlayerPane[\s\S]*variant="compact"[\s\S]*active=\{true\}/);
assert.equal(source.includes('usePlaybackProgress'), false);
assert.equal(source.includes('setInterval'), false);

const miniBodyStart = source.indexOf('const MiniPlayerStaticBody = React.memo');
const playbackMeterStart = source.indexOf('const PlaybackMeter =');
assert.ok(miniBodyStart >= 0);
assert.ok(playbackMeterStart > miniBodyStart);
const miniBody = source.slice(miniBodyStart, playbackMeterStart);
assert.match(miniBody, /formatMiniTrackSubtitle\(player\.artist, player\.album\)/);
assert.match(miniBody, /justifyContent="center"/);
assert.match(miniBody, /paddingLeft=\{layout\.infoLeftPadding\}/);
assert.match(miniBody, /<Text bold color=\{BORDER_BLUE_SOFT\} wrap="truncate-end">\{player\.name\}<\/Text>/);
assert.match(miniBody, /<Text color="#ffffff" wrap="truncate-end">\{formatMiniTrackSubtitle\(player\.artist, player\.album\)\}<\/Text>/);
assert.equal(miniBody.includes('Now Playing'), false);
assert.equal(miniBody.includes('playing'), false);
assert.equal(miniBody.includes('paused'), false);

const staticCoverStart = source.indexOf('const StaticCover = React.memo');
assert.ok(staticCoverStart >= 0);
assert.ok(miniBodyStart > staticCoverStart);
const staticCover = source.slice(staticCoverStart, miniBodyStart);
assert.match(staticCover, /alignItems="center" justifyContent=\{compact \? 'flex-end' : 'center'\}/);
assert.match(source, /const MINI_COVER_PATTERN_MAX_SIZE = 80/);
assert.match(staticCover, /const maxSize = maxPatternSize \?\? \(compact \? MINI_COVER_PATTERN_MAX_SIZE : 32\)/);
assert.match(staticCover, /const patternDisplay = coverPattern/);
assert.match(staticCover, /const fetchableCoverUrl = patternDisplay\.status === 'none'/);
assert.match(staticCover, /if \(patternDisplay\.status === 'unfit'\)/);
assert.match(miniBody, /alignItems="center"\s+justifyContent="flex-end"/);

const miniStart = source.indexOf('const MiniPlayerRegion =');
const conversationStart = source.indexOf('const ConversationRegion =');
assert.ok(miniStart >= 0);
assert.ok(conversationStart > miniStart);
const miniRegion = source.slice(miniStart, conversationStart);
assert.match(miniRegion, /padding=\{0\}/);
assert.equal(miniRegion.includes('borderStyle='), false);
assert.equal(miniRegion.includes('<ConversationColumn'), false);
assert.equal(miniRegion.includes('<InputDock'), false);
assert.equal(miniRegion.includes('<HeaderFrame'), false);

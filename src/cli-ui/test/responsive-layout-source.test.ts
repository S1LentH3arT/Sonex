import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.equal(appSource.includes('<Static items={bannerItems}>'), false);
assert.match(appSource, /resolveChatHeaderVariant/);
assert.match(appSource, /usePlaybackProgressWriter/);
assert.equal(appSource.includes('useMiniProgressWriter'), false);
assert.match(appSource, /setTimeout\([\s\S]*80/);
assert.match(appSource, /clearTerminalForLayoutSwitch\(stdout\);[\s\S]*setMiniSnapshotRevision/);
assert.equal(appSource.includes('terminalSize.rows - 8'), false);
assert.equal(appSource.includes('terminalSize.columns - 4'), false);

assert.match(componentSource, /resolveMiniPlayerLayout/);
assert.match(componentSource, /wrap="truncate-end"/);
assert.match(componentSource, /measureElement\(containerRef\.current\)/);
assert.match(componentSource, /width[^\n]*height/);
assert.equal(componentSource.includes('<MiniPlaybackMeter'), false);

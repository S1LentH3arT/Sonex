import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../dist/components.js', import.meta.url), 'utf8');

assert.match(source, /const TrackPanelRegion =/);
assert.match(source, /return _jsx\(TrackPanelRegion, \{ trackPanel: trackPanel \}\);/);

const conversationRegionStart = source.indexOf('const ConversationRegion =');
const dynamicShellStart = source.indexOf('export const DynamicShell =');
assert.ok(conversationRegionStart >= 0);
assert.ok(dynamicShellStart > conversationRegionStart);
const conversationRegion = source.slice(conversationRegionStart, dynamicShellStart);
assert.equal(conversationRegion.includes('InputDock'), false);

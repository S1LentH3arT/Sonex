import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../dist/components.js', import.meta.url), 'utf8');

assert.match(source, /const TrackPanelOverlay =/);
assert.match(source, /return _jsx\(TrackPanelOverlay, \{ trackPanel: trackPanel \}\);/);
assert.doesNotMatch(source, /children: "Conversation"/);

const conversationRegionStart = source.indexOf('const ConversationRegion =');
const dynamicShellStart = source.indexOf('export const DynamicShell =');
assert.ok(conversationRegionStart >= 0);
assert.ok(dynamicShellStart > conversationRegionStart);
const conversationRegion = source.slice(conversationRegionStart, dynamicShellStart);
assert.equal(conversationRegion.includes('InputDock'), false);

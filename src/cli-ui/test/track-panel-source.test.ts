import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.match(source, /const TrackPanelRegion =/);

const trackPanelRegionStart = source.indexOf('const TrackPanelRegion =');
const conversationColumnStart = source.indexOf('const ConversationColumn =');
const conversationRegionStart = source.indexOf('const ConversationRegion =');
assert.ok(trackPanelRegionStart >= 0);
assert.ok(conversationColumnStart > trackPanelRegionStart);
assert.ok(conversationRegionStart > conversationColumnStart);
const trackPanelRegion = source.slice(trackPanelRegionStart, conversationColumnStart);
assert.match(trackPanelRegion, /<TrackPanel panel=\{trackPanel\} expanded=\{true\} \/>/);
assert.equal(trackPanelRegion.includes('<ChatPane'), false);
assert.equal(trackPanelRegion.includes('<InputDock'), false);

const dynamicShellStart = source.indexOf('export const DynamicShell =');
assert.ok(dynamicShellStart > conversationRegionStart);
const conversationRegion = source.slice(conversationRegionStart, dynamicShellStart);
assert.match(conversationRegion, /if \(trackPanel\) \{/);
assert.match(conversationRegion, /<TrackPanelRegion trackPanel=\{trackPanel\} \/>/);
assert.match(conversationRegion, /<ConversationColumn/);

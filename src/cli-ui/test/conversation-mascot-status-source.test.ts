import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

const mascotStart = source.indexOf('const MiniMascotStatus =');
assert.ok(mascotStart >= 0);
const conversationStart = source.indexOf('const ConversationColumn =');
assert.ok(conversationStart > mascotStart);
const regionStart = source.indexOf('const ConversationRegion =');
assert.ok(regionStart > conversationStart);

const mascotBody = source.slice(mascotStart, conversationStart);
assert.match(mascotBody, /height=\{2\}/);
assert.match(mascotBody, /SONEX_MASCOT_MICRO\.map/);

const conversationBody = source.slice(conversationStart, regionStart);
assert.match(conversationBody, /<ChatPane[\s\S]*\/>\s*<MiniMascotStatus \/>\s*<InputDock/);
assert.equal(conversationBody.includes('{statusText}'), false);
assert.equal(conversationBody.includes('showRunMetrics'), false);
assert.equal(conversationBody.includes('{elapsed}'), false);
assert.equal(conversationBody.includes('{tokens}'), false);

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { SONEX_MASCOT_MICRO } from '../src/constants.js';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const source = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

const mascotStart = source.indexOf('const MiniMascotStatus =');
assert.ok(mascotStart >= 0);
const mascotEnd = source.indexOf('\n};', mascotStart);
assert.ok(mascotEnd > mascotStart);
const conversationStart = source.indexOf('const ConversationColumn =');
assert.ok(conversationStart > mascotStart);
const regionStart = source.indexOf('const ConversationRegion =');
assert.ok(regionStart > conversationStart);

const mascotBody = source.slice(mascotStart, mascotEnd);
assert.match(mascotBody, /height=\{1\}/);
assert.match(mascotBody, /alignItems="flex-start"/);
assert.match(mascotBody, /paddingLeft=\{1\}/);
assert.match(mascotBody, /paddingRight=\{1\}/);
assert.match(mascotBody, /SONEX_MASCOT_MICRO\.map/);
assert.equal(mascotBody.includes('marginBottom'), false);
assert.equal(mascotBody.includes('marginTop'), false);
assert.equal(SONEX_MASCOT_MICRO.length, 1);

const conversationBody = source.slice(conversationStart, regionStart);
assert.match(conversationBody, /<ChatPane[\s\S]*\/>\s*<MiniMascotStatus \/>\s*<InputDock/);
assert.equal(conversationBody.includes('{statusText}'), false);
assert.equal(conversationBody.includes('showRunMetrics'), false);
assert.equal(conversationBody.includes('{elapsed}'), false);
assert.equal(conversationBody.includes('{tokens}'), false);
assert.equal(appSource.includes('formatElapsed'), false);
assert.equal(appSource.includes('showRunMetrics'), false);
assert.equal(appSource.includes('setElapsed'), false);
assert.equal(appSource.includes('setTokens'), false);
assert.equal(source.includes('showRunMetrics'), false);
assert.equal(source.includes('elapsed: string | null'), false);
assert.equal(source.includes('tokens: string | null'), false);

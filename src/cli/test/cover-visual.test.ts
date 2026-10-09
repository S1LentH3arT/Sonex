import assert from 'node:assert/strict';

import {
    coverVisualFromSource,
    rhythmFrameForPlayback,
} from '../src/cover-visual.js';

const visual = coverVisualFromSource('https://example.com/covers/lunar-glass.jpg');
const sameVisual = coverVisualFromSource('https://example.com/covers/lunar-glass.jpg');
const differentVisual = coverVisualFromSource('https://example.com/covers/oxide-night.jpg');

assert.equal(visual.status, 'ready');
assert.match(visual.primary, /^#[0-9a-f]{6}$/);
assert.match(visual.secondary, /^#[0-9a-f]{6}$/);
assert.equal(visual.blocks.length, 8);
assert.equal(visual.blocks[0]?.length, 14);
assert.deepEqual(visual, sameVisual);
assert.notEqual(visual.primary, differentVisual.primary);

const fallback = coverVisualFromSource(null, true);

assert.equal(fallback.status, 'fallback');
assert.equal(fallback.blocks.length, 8);
assert.equal(fallback.blocks[0]?.length, 14);
assert.match(fallback.accent, /^#[0-9a-f]{6}$/);

const playingFrameEarly = rhythmFrameForPlayback(true, 1500, visual.seed);
const playingFrameLater = rhythmFrameForPlayback(true, 3200, visual.seed);
const pausedFrameEarly = rhythmFrameForPlayback(false, 1500, visual.seed);
const pausedFrameLater = rhythmFrameForPlayback(false, 3200, visual.seed);

assert.notEqual(playingFrameEarly, playingFrameLater);
assert.equal(pausedFrameEarly, pausedFrameLater);
assert.ok(playingFrameEarly >= 0 && playingFrameEarly <= 3);
assert.ok(playingFrameLater >= 0 && playingFrameLater <= 3);

import assert from 'node:assert/strict';

import {
    coverVisualFromSource,
    rhythmFrameForPlayback,
} from '../src/cover-visual.js';

/**
 * Defines the visual constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/cover-visual.test.ts.
 */
const visual = coverVisualFromSource('https://example.com/covers/lunar-glass.jpg');
/**
 * Defines the same visual constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/cover-visual.test.ts.
 */
const sameVisual = coverVisualFromSource('https://example.com/covers/lunar-glass.jpg');
/**
 * Defines the different visual constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/cover-visual.test.ts.
 */
const differentVisual = coverVisualFromSource('https://example.com/covers/oxide-night.jpg');

assert.equal(visual.status, 'ready');
assert.match(visual.primary, /^#[0-9a-f]{6}$/);
assert.match(visual.secondary, /^#[0-9a-f]{6}$/);
assert.equal(visual.blocks.length, 8);
assert.equal(visual.blocks[0]?.length, 14);
assert.deepEqual(visual, sameVisual);
assert.notEqual(visual.primary, differentVisual.primary);

/**
 * Defines the fallback constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/cover-visual.test.ts.
 */
const fallback = coverVisualFromSource(null, true);

assert.equal(fallback.status, 'fallback');
assert.equal(fallback.blocks.length, 8);
assert.equal(fallback.blocks[0]?.length, 14);
assert.match(fallback.accent, /^#[0-9a-f]{6}$/);

/**
 * Defines the playing frame early constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/cover-visual.test.ts.
 */
const playingFrameEarly = rhythmFrameForPlayback(true, 1500, visual.seed);
/**
 * Defines the playing frame later constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/cover-visual.test.ts.
 */
const playingFrameLater = rhythmFrameForPlayback(true, 3200, visual.seed);
/**
 * Defines the paused frame early constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/cover-visual.test.ts.
 */
const pausedFrameEarly = rhythmFrameForPlayback(false, 1500, visual.seed);
/**
 * Defines the paused frame later constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/cover-visual.test.ts.
 */
const pausedFrameLater = rhythmFrameForPlayback(false, 3200, visual.seed);

assert.notEqual(playingFrameEarly, playingFrameLater);
assert.equal(pausedFrameEarly, pausedFrameLater);
assert.ok(playingFrameEarly >= 0 && playingFrameEarly <= 3);
assert.ok(playingFrameLater >= 0 && playingFrameLater <= 3);

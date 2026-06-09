import assert from 'node:assert/strict';

import {
    buildMiniProgressLine,
    resolveMiniProgressPosition,
    writeTerminalLine,
} from '../src/mini-progress.js';
import type { PlayerState } from '../src/types.js';

/**
 * Defines the playing constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/mini-progress.test.ts.
 */
const playing: PlayerState = {
    name: 'Track',
    artist: 'Artist',
    album: 'Album',
    duration_ms: 120_000,
    progress_ms: 30_000,
    timestamp: 1_000,
    is_playing: true,
};

assert.equal(
    buildMiniProgressLine(playing, 2_000, 22),
    '0:31 ━━━───────── 2:00',
);

assert.equal(
    buildMiniProgressLine({ ...playing, duration_ms: 0 }, 2_000, 22),
    '0:31 ──────────── 0:00',
);

assert.deepEqual(
    resolveMiniProgressPosition({ columns: 40, rows: 20 }),
    { row: 18, column: 3, width: 34 },
);

assert.equal(resolveMiniProgressPosition({ columns: null, rows: 20 }), null);
assert.equal(resolveMiniProgressPosition({ columns: 40, rows: null }), null);

/**
 * Defines the writes constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/mini-progress.test.ts.
 */
const writes: string[] = [];
writeTerminalLine(
    {
        write(chunk: string) {
            writes.push(chunk);
        },
    },
    { row: 18, column: 3, width: 12 },
    'abc',
);

assert.deepEqual(writes, ['\u001B7\u001B[18;3H\u001B[2Kabc         \u001B8']);

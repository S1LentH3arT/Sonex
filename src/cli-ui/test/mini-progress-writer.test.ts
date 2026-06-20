import assert from 'node:assert/strict';

import {
    buildPlaybackProgressLine,
    buildPlaybackStatusIconLine,
    resolvePlaybackProgressUpdateMode,
    shouldRefreshMiniSnapshot,
    writeTerminalLine,
} from '../src/mini-progress-writer.js';
import { PLAYBACK_PROGRESS_INTERVAL_MS } from '../src/hooks.js';
import { resolveMiniPlayerLayout } from '../src/layout.js';
import type { PlayerState } from '../src/types.js';

const playing: PlayerState = {
    name: 'Track',
    artist: 'Artist',
    album: 'Album',
    duration_ms: 120_000,
    progress_ms: 30_000,
    timestamp: 1_000,
    is_playing: true,
};

assert.equal(PLAYBACK_PROGRESS_INTERVAL_MS, 1000);
assert.equal(resolvePlaybackProgressUpdateMode(false, playing), 'off');
assert.equal(resolvePlaybackProgressUpdateMode(true, playing), 'interval');
assert.equal(resolvePlaybackProgressUpdateMode(true, { ...playing, is_playing: false }), 'once');
assert.equal(resolvePlaybackProgressUpdateMode(true, { ...playing, ended: true }), 'off');

assert.equal(shouldRefreshMiniSnapshot('resize'), true);
assert.equal(shouldRefreshMiniSnapshot('region'), true);
assert.equal(shouldRefreshMiniSnapshot('player'), false);
assert.equal(shouldRefreshMiniSnapshot('cover'), false);

assert.equal(buildPlaybackProgressLine(playing, 2_000, 22), '0:31 ━━━───────── 2:00');
assert.equal(buildPlaybackStatusIconLine(playing, 6).trim(), '▶ ⢿⡿');
assert.equal(buildPlaybackStatusIconLine({ ...playing, is_playing: false }, 6).trim(), '▌▌ ⢿⡿');
assert.equal(buildPlaybackStatusIconLine(playing, 22), '         ▶ ⢿⡿');
assert.equal(buildPlaybackStatusIconLine({ ...playing, is_playing: false, is_liked: true }, 22), '        ▌▌ ⣿⣿');

const position = resolveMiniPlayerLayout({ columns: 88, rows: 32 }).progressSlot;
assert.deepEqual(position, { row: 17, column: 5, width: 23 });
const writes: string[] = [];
writeTerminalLine({ write: (chunk: string) => writes.push(chunk) }, position, 'abc');
assert.deepEqual(writes, [`\u001B7\u001B[${position.row};${position.column}Habc${' '.repeat(position.width - 3)}\u001B8`]);

import assert from 'node:assert/strict';

import {
    buildPlaybackProgressLine,
    buildPlaybackStatusIconLine,
    playbackStatusIconSegments,
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
assert.equal(resolvePlaybackProgressUpdateMode(true, { ...playing, playback_status: 'starting' }), 'once');
assert.equal(resolvePlaybackProgressUpdateMode(true, { ...playing, playback_status: 'syncing', progress_sync_lost: true }), 'once');
assert.equal(resolvePlaybackProgressUpdateMode(true, { ...playing, playback_status: 'buffering', paused_for_cache: true }), 'once');
assert.equal(resolvePlaybackProgressUpdateMode(true, { ...playing, is_playing: false }), 'once');
assert.equal(resolvePlaybackProgressUpdateMode(true, { ...playing, ended: true }), 'off');

assert.equal(shouldRefreshMiniSnapshot('resize'), true);
assert.equal(shouldRefreshMiniSnapshot('region'), true);
assert.equal(shouldRefreshMiniSnapshot('player'), false);
assert.equal(shouldRefreshMiniSnapshot('cover'), false);

assert.equal(buildPlaybackProgressLine(playing, 2_000, 22), '0:31 ━━━───────── 2:00');
assert.equal(buildPlaybackProgressLine({ ...playing, progress_ms: 0, playback_status: 'starting' }, 2_000, 22), 'starting ──────── 2:00');
assert.equal(buildPlaybackProgressLine({ ...playing, playback_status: 'syncing', progress_sync_lost: true }, 2_000, 22), 'syncing ━━─────── 2:00');
assert.equal(buildPlaybackProgressLine({ ...playing, playback_status: 'buffering', paused_for_cache: true }, 2_000, 22), 'buffering ━╸───── 2:00');
assert.equal(buildPlaybackProgressLine({ ...playing, diagnostic_notice: 'clock_drift' }, 2_000, 22), 'diagnostic ━╸──── 2:00');
assert.equal(buildPlaybackStatusIconLine(playing, 22, 2_000).text, '          ▶ +');
assert.equal(buildPlaybackStatusIconLine({ ...playing, is_playing: false, is_in_playlist: true }, 22, 2_000).text, '          ▌▌ ✔');
assert.equal(buildPlaybackStatusIconLine(playing, 1, 2_000).text, '▶');
assert.deepEqual(playbackStatusIconSegments({ ...playing, is_in_playlist: true }, 22, 2_000), [
    { text: '          ' },
    { text: '▶' },
    { text: ' ' },
    { text: '✔', color: 'green' },
]);

const position = resolveMiniPlayerLayout({ columns: 88, rows: 32 }).progressSlot;
assert.deepEqual(position, { row: 17, column: 5, width: 23 });
const writes: string[] = [];
writeTerminalLine({ write: (chunk: string) => writes.push(chunk) }, position, 'abc');
assert.deepEqual(writes, [`\u001B7\u001B[${position.row};${position.column}Habc${' '.repeat(position.width - 3)}\u001B8`]);
writeTerminalLine({ write: (chunk: string) => writes.push(chunk) }, { ...position, width: 22 }, buildPlaybackStatusIconLine({ ...playing, is_in_playlist: true }, 22, 2_000));
assert.equal(writes.at(-1), `\u001B7\u001B[${position.row};${position.column}H          ▶ \u001B[32m✔\u001B[39m${' '.repeat(9)}\u001B8`);

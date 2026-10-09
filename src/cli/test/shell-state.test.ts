import assert from 'node:assert/strict';
import test from 'node:test';

import { initialShellState, planShellSurfaceTransition, reduceShellState, surfaceForShellRegion } from '../src/shell-state.js';

const playing = {
    name: 'Song', artist: 'Artist', album: 'Album', duration_ms: 1000,
    progress_ms: 0, is_playing: true,
};

test('player events enter and leave the mini player through one state transition', () => {
    const active = reduceShellState(initialShellState, { type: 'player_event', player: playing });
    assert.deepEqual(active, { region: 'miniPlayer', playbackSessionActive: true });
    assert.deepEqual(
        reduceShellState(active, { type: 'player_event', player: { ...playing, ended: true, is_playing: false } }),
        initialShellState,
    );
});

test('toggle transitions honor immersive provider mode', () => {
    const active = { region: 'chat' as const, playbackSessionActive: true };
    assert.equal(
        reduceShellState(active, { type: 'toggle_region', providerModeEnabled: true }).region,
        'providerImmersive',
    );
});

test('set_region preserves playback session state', () => {
    const active = { region: 'miniPlayer' as const, playbackSessionActive: true };
    assert.deepEqual(
        reduceShellState(active, { type: 'set_region', region: 'chat' }),
        { region: 'chat', playbackSessionActive: true },
    );
});

test('surface mapping keeps chat and memory on the main surface', () => {
    assert.equal(surfaceForShellRegion('chat'), 'main');
    assert.equal(surfaceForShellRegion('memoryPanel'), 'main');
    assert.equal(surfaceForShellRegion('miniPlayer'), 'alternate');
});

test('surface transition planning is a no-op for the same region', () => {
    assert.deepEqual(planShellSurfaceTransition('chat', 'chat'), { changed: false, target: 'main' });
    assert.deepEqual(planShellSurfaceTransition('chat', 'miniPlayer'), { changed: true, target: 'alternate' });
});

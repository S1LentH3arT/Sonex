import assert from 'node:assert/strict';
import test from 'node:test';
import { planServerEventCoordination } from '../src/event-coordination.js';

test('panel events coordinate region and lifecycle through one seam', () => {
    assert.deepEqual(
        planServerEventCoordination({ type: 'track_panel', panel: 'queue', title: 'Queue', tracks: [] }),
        { region: 'trackPanel' },
    );
    assert.deepEqual(
        planServerEventCoordination({ type: 'extension_panel', view: 'list', title: 'Extensions', extensions: [] }),
        { panelLifecycle: 'extension_event' },
    );
    assert.deepEqual(
        planServerEventCoordination({ type: 'help_panel', title: 'Help', hint: 'Esc', commands: [] }),
        { region: 'chat', panelLifecycle: 'help_event' },
    );
});

test('inactive setup events close owned panels without forcing a region switch', () => {
    assert.deepEqual(
        planServerEventCoordination({
            type: 'auth_setup',
            provider: 'openai',
            step: 'model',
            title: 'Done',
            message: 'Done',
            active: false,
        }),
        { panelLifecycle: 'setup_event' },
    );
});

test('player coordination owns the shell transition calculation', () => {
    const coordination = planServerEventCoordination(
        {
            type: 'player',
            state: { name: 'Song', artist: 'Artist', album: 'Album', duration_ms: 1, progress_ms: 0, is_playing: true },
        },
        { shellState: { region: 'chat', playbackSessionActive: false } },
    );
    assert.deepEqual(coordination.shellState, { region: 'miniPlayer', playbackSessionActive: true });
    assert.equal(coordination.region, 'miniPlayer');
});

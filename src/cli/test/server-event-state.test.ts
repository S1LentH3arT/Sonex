import assert from 'node:assert/strict';
import test from 'node:test';
import { initialServerEventState, reduceServerEventState } from '../src/server-event-state.js';

test('reduces panel, queue, cover, confirmation, and auth events without UI side effects', () => {
    let state = reduceServerEventState(initialServerEventState, {
        type: 'event',
        language: 'en',
        event: { type: 'queue', tracks: [{ index: '1', title: 'Queued', artist: 'Artist', duration: '1:00' }] },
    });
    state = reduceServerEventState(state, {
        type: 'event',
        language: 'en',
        event: { type: 'track_panel', panel: 'queue', title: 'Queue', tracks: [{ index: '1', title: 'Queued', artist: 'Artist', duration: '1:00' }] },
    });
    assert.equal(state.trackPanel?.tracks[0]?.queued, true);

    state = reduceServerEventState(state, {
        type: 'event',
        language: 'en',
        event: { type: 'cover', url: 'cover-a' },
    });
    state = reduceServerEventState(state, {
        type: 'event',
        language: 'en',
        event: { type: 'cover_image', source_url: 'cover-a', format: 'png', width: 100, height: 100, data: 'encoded' },
    });
    assert.equal(state.coverImage?.source_url, 'cover-a');
    state = reduceServerEventState(state, {
        type: 'event',
        language: 'en',
        event: { type: 'cover_pattern', source_url: 'cover-a', palette: ['#fff'], variants: {} },
    });
    assert.equal(state.coverPattern?.source_url, 'cover-a');

    state = reduceServerEventState(state, {
        type: 'event',
        language: 'en',
        event: { type: 'confirm', id: 'confirm-1', tool_name: 'play', tool_args: {} },
    });
    assert.equal(state.confirm?.id, 'confirm-1');
    state = reduceServerEventState(state, {
        type: 'event',
        language: 'en',
        event: { type: 'confirm_dismiss', id: 'confirm-1' },
    });
    assert.equal(state.confirm, null);

    state = reduceServerEventState(state, {
        type: 'event',
        language: 'en',
        event: { type: 'auth_state', ready: true, provider: 'openai', model: 'gpt', auth_type: 'api_key', credential_source: 'env' },
    });
    assert.equal(state.authState.ready, true);
});

test('ignores stale cover patterns and dismissed confirmations', () => {
    let state = reduceServerEventState(initialServerEventState, {
        type: 'event',
        language: 'en',
        event: { type: 'cover', url: 'current' },
    });
    state = reduceServerEventState(state, {
        type: 'event',
        language: 'en',
        event: { type: 'cover_pattern', source_url: 'stale', palette: [], variants: {} },
    });
    assert.equal(state.coverPattern, null);
    state = reduceServerEventState(state, {
        type: 'event',
        language: 'en',
        dismissedConfirm: true,
        event: { type: 'confirm', id: 'dismissed', tool_name: 'play', tool_args: {} },
    });
    assert.equal(state.confirm, null);
});

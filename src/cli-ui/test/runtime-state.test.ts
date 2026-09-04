import assert from 'node:assert/strict';
import test from 'node:test';

import { createInitialRuntimeState, reduceRuntimeState } from '../src/runtime-state.js';

test('runtime events update session, usage, and working state together', () => {
    let state = createInitialRuntimeState('Snoozing');
    state = reduceRuntimeState(state, { type: 'event', event: { type: 'session_state', session_id: 's1' } });
    state = reduceRuntimeState(state, { type: 'event', event: { type: 'usage_state', input_tokens: 3, output_tokens: 5 } });
    state = reduceRuntimeState(state, { type: 'event', event: { type: 'agent_working_state', turn_id: 't1', active: true } });

    assert.equal(state.sessionId, 's1');
    assert.deepEqual(state.tokenUsage, { inputTokens: 3, outputTokens: 5 });
    assert.equal(state.agentWorkingTurnId, 't1');
});

test('activity and status events own launch-preparing transitions', () => {
    let state = createInitialRuntimeState('Snoozing');
    const pending = {
        type: 'activity' as const,
        id: 'a1',
        kind: 'tool' as const,
        title: 'Searching Spotify',
        status: 'pending' as const,
        timestamp: 1,
    };
    state = reduceRuntimeState(state, { type: 'event', event: pending });
    assert.equal(state.launchPreparing, true);
    state = reduceRuntimeState(state, {
        type: 'event',
        event: { ...pending, status: 'success' },
    });
    assert.equal(state.launchPreparing, false);
    state = reduceRuntimeState(state, {
        type: 'event',
        event: { type: 'status', phase: 'playback', message: '正在准备播放...', active: true },
        rawEvent: { type: 'status', phase: 'playback', message: 'Preparing playback...', active: true },
    });
    assert.equal(state.statusText, '正在准备播放...');
    assert.equal(state.launchPreparing, true);
});

test('recommendation lock and optimistic interrupt are reducer actions', () => {
    let state = createInitialRuntimeState('Snoozing');
    state = reduceRuntimeState(state, { type: 'event', event: { type: 'agent_working_state', turn_id: 't1', active: true } });
    state = reduceRuntimeState(state, { type: 'event', event: { type: 'input_state', disabled: true, reason: 'recommendation' } });
    assert.equal(state.recommendInputLocked, true);
    state = reduceRuntimeState(state, { type: 'clear_agent_working' });
    assert.equal(state.agentWorkingTurnId, null);
});

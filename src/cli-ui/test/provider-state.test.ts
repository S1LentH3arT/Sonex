import assert from 'node:assert/strict';
import test from 'node:test';

import { initialProviderState, reduceProviderState } from '../src/provider-state.js';

test('provider events update mode and setup state through one reducer', () => {
    let state = reduceProviderState(initialProviderState, {
        type: 'event',
        event: { type: 'provider_mode', provider: 'spotify', enabled: true, connection_status: 'connected' },
    });
    state = reduceProviderState(state, {
        type: 'event',
        event: { type: 'spotify_setup', step: 'login', title: 'Login', message: 'Continue', active: true },
    });

    assert.deepEqual(state.providerMode, { provider: 'spotify', enabled: true, connection_status: 'connected' });
    assert.equal(state.spotifySetup?.active, true);
});

test('auth model completion closes setup while ordinary inactive steps remain visible', () => {
    const active = reduceProviderState(initialProviderState, {
        type: 'event',
        event: { type: 'auth_setup', provider: 'openai', step: 'provider', title: 'Provider', message: 'Choose', active: true },
    });
    assert.equal(active.authSetup?.active, true);

    const closed = reduceProviderState(active, {
        type: 'event',
        event: { type: 'auth_setup', provider: 'openai', step: 'model', title: 'Done', message: 'Ready', active: false },
    });
    assert.equal(closed.authSetup, null);
});

test('setup cancellation clears only its owning setup state', () => {
    const state = reduceProviderState(
        reduceProviderState(initialProviderState, {
            type: 'event',
            event: { type: 'spotify_setup', step: 'login', title: 'Login', message: 'Continue', active: true },
        }),
        { type: 'clear_spotify_setup' },
    );
    assert.equal(state.spotifySetup, null);
    assert.equal(state.authSetup, null);
});

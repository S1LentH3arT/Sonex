import assert from 'node:assert/strict';
import test from 'node:test';
import { planPanelLifecycle } from '../src/panel-lifecycle.js';

test('input-like transitions close transient panels and reset their selections', () => {
    assert.deepEqual(planPanelLifecycle('input'), {
        close: ['help', 'track', 'language'],
        resetSelection: ['help', 'track'],
    });
    assert.deepEqual(planPanelLifecycle('safe_exit'), planPanelLifecycle('input'));
});

test('panel events preserve the existing ownership rules', () => {
    assert.deepEqual(planPanelLifecycle('extension_event'), {
        close: ['track', 'memory', 'help', 'language'],
        resetSelection: [],
    });
    assert.deepEqual(planPanelLifecycle('help_event'), {
        close: ['track', 'language'],
        resetSelection: ['help'],
    });
});

test('setup and bye transitions only clear panels they previously owned', () => {
    assert.deepEqual(planPanelLifecycle('setup_event'), { close: ['help'], resetSelection: ['help'] });
    assert.deepEqual(planPanelLifecycle('bye'), { close: ['help', 'track'], resetSelection: ['help', 'track'] });
});

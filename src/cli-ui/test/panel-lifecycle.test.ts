import assert from 'node:assert/strict';
import test from 'node:test';
import { applyPanelLifecycle, planPanelLifecycle } from '../src/panel-lifecycle.js';

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

test('applies lifecycle policy through the panel seam', () => {
    const closed: string[] = [];
    const reset: string[] = [];
    applyPanelLifecycle('extension_event', {
        close: (panel) => closed.push(panel),
        resetSelection: (panel) => reset.push(panel),
    });
    assert.deepEqual(closed, ['track', 'memory', 'help', 'language']);
    assert.deepEqual(reset, []);
});

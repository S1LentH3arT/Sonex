import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveInputRoute } from '../src/input-routing.js';

const baseContext = {
    confirm: null,
    selectedConfirmChoice: null,
    selectableConfirmChoices: [],
    extensionPanelActive: false,
    extensionInputFocused: false,
    extensionSetupInput: null,
    authSetupActive: false,
    spotifySetupActive: false,
    selectedSlashCommand: undefined,
};

test('input routing preserves precedence for confirmation and extension input', () => {
    assert.deepEqual(
        resolveInputRoute('yes', {
            ...baseContext,
            confirm: { id: 'c1', tool_name: 'play', tool_args: {}, message: 'Confirm', choices: [{ value: 'yes', label: 'Yes' }] },
            selectableConfirmChoices: [{ value: 'yes', label: 'Yes' }],
        }),
        { type: 'confirm', decision: 'yes' },
    );
    assert.deepEqual(
        resolveInputRoute('secret', {
            ...baseContext,
            extensionPanelActive: true,
            extensionInputFocused: true,
            extensionSetupInput: { placeholder: 'Secret', mask: true },
        }),
        { type: 'extension_input', value: 'secret' },
    );
});

test('input routing resolves local commands before backend input', () => {
    assert.deepEqual(resolveInputRoute('/exit', baseContext), { type: 'safe_exit', reason: 'exit' });
    assert.deepEqual(resolveInputRoute('/info', baseContext), { type: 'info' });
    assert.deepEqual(resolveInputRoute('/unknown', baseContext), { type: 'unknown_slash', value: '/unknown' });
    assert.deepEqual(resolveInputRoute('hello', baseContext), { type: 'user_input', value: 'hello', command: undefined });
});

test('input routing directs setup text to its owning channel', () => {
    assert.deepEqual(
        resolveInputRoute('spotify setup', { ...baseContext, spotifySetupActive: true }),
        { type: 'setup_input', channel: 'spotify', value: 'spotify setup' },
    );
    assert.deepEqual(
        resolveInputRoute('api key', { ...baseContext, authSetupActive: true }),
        { type: 'setup_input', channel: 'auth', value: 'api key' },
    );
});

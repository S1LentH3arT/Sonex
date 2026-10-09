import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveLoginProviderSelectionIndex } from '../src/login-navigation.js';

const providers = [
    { value: 'openai', label: 'OpenAI', connection_status: 'missing' as const },
    { value: 'deepseek', label: 'DeepSeek', connection_status: 'active' as const },
    { value: 'xai', label: 'xAI', connection_status: 'saved' as const },
];

test('selects the current provider when returning to the provider list', () => {
    assert.equal(resolveLoginProviderSelectionIndex(providers, 'xai'), 2);
});

test('falls back to the active provider and then the first provider', () => {
    assert.equal(resolveLoginProviderSelectionIndex(providers, 'unknown'), 1);
    assert.equal(resolveLoginProviderSelectionIndex(providers.slice(0, 1), 'unknown'), 0);
});

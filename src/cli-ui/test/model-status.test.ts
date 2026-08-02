import assert from 'node:assert/strict';
import test from 'node:test';

import { formatModelStatus } from '../src/model-status.js';

test('formats supported provider brands', () => {
    const cases = [
        ['openai', 'OpenAI'],
        ['anthropic', 'Anthropic'],
        ['gemini', 'Google Gemini'],
        ['deepseek', 'DeepSeek'],
        ['openrouter', 'OpenRouter'],
        ['zai', 'Z.AI'],
        ['kimi_global', 'Kimi Global'],
        ['kimi_cn', 'Kimi CN'],
        ['minimax_global', 'MiniMax Global'],
        ['minimax_cn', 'MiniMax CN'],
        ['xai', 'xAI'],
        ['custom', 'Custom'],
    ] as const;

    for (const [provider, label] of cases) {
        assert.equal(
            formatModelStatus({ ready: true, provider, model: 'model-name' }),
            `[${label}] model-name`,
        );
    }
});

test('normalizes provider casing and trims provider and model', () => {
    assert.equal(
        formatModelStatus({
            ready: true,
            provider: '  OPENAI  ',
            model: '  gpt-5.5  ',
        }),
        '[OpenAI] gpt-5.5',
    );
});

test('prefers the explicit official model display name', () => {
    assert.equal(
        formatModelStatus({
            ready: true,
            provider: 'anthropic',
            model: 'claude-sonnet-4-6',
            model_label: 'Claude Sonnet 4.6',
        }),
        '[Anthropic] Claude Sonnet 4.6',
    );
});

test('preserves a trimmed unknown provider label', () => {
    assert.equal(
        formatModelStatus({
            ready: true,
            provider: '  custom-provider  ',
            model: 'custom-model',
        }),
        '[custom-provider] custom-model',
    );
});

test('hides model status until authentication data is ready and complete', () => {
    assert.equal(
        formatModelStatus({ ready: false, provider: 'openai', model: 'gpt-5.5' }),
        null,
    );
    assert.equal(
        formatModelStatus({ ready: true, provider: '   ', model: 'gpt-5.5' }),
        null,
    );
    assert.equal(
        formatModelStatus({ ready: true, provider: 'openai', model: '   ' }),
        null,
    );
});

import assert from 'node:assert/strict';
import test from 'node:test';

import { formatModelStatus, formatTokenCount } from '../src/model-status.js';

const emptyUsage = { inputTokens: 0, outputTokens: 0 };

test('formats token counts with a floor-rounded k suffix above one thousand', () => {
    assert.equal(formatTokenCount(0), '0');
    assert.equal(formatTokenCount(1_000), '1000');
    assert.equal(formatTokenCount(1_001), '1k');
    assert.equal(formatTokenCount(12_999), '12k');
});

test('prefixes the model status with cumulative input and output usage', () => {
    assert.equal(
        formatModelStatus(
            { ready: true, provider: 'deepseek', model: 'DeepSeek-V4-Flash' },
            { inputTokens: 12_999, outputTokens: 2_999 },
        ),
        '↑12k ↓2k [DeepSeek] DeepSeek-V4-Flash',
    );
});

test('shows only the model before the session reports any token usage', () => {
    assert.equal(
        formatModelStatus(
            { ready: true, provider: 'deepseek', model: 'DeepSeek-V4-Flash' },
            emptyUsage,
        ),
        '[DeepSeek] DeepSeek-V4-Flash',
    );
});

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
            formatModelStatus({ ready: true, provider, model: 'model-name' }, emptyUsage),
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
        }, emptyUsage),
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
        }, emptyUsage),
        '[Anthropic] Claude Sonnet 4.6',
    );
});

test('preserves a trimmed unknown provider label', () => {
    assert.equal(
        formatModelStatus({
            ready: true,
            provider: '  custom-provider  ',
            model: 'custom-model',
        }, emptyUsage),
        '[custom-provider] custom-model',
    );
});

test('hides model status until authentication data is ready and complete', () => {
    assert.equal(
        formatModelStatus({ ready: false, provider: 'openai', model: 'gpt-5.5' }, emptyUsage),
        null,
    );
    assert.equal(
        formatModelStatus({ ready: true, provider: '   ', model: 'gpt-5.5' }, emptyUsage),
        null,
    );
    assert.equal(
        formatModelStatus({ ready: true, provider: 'openai', model: '   ' }, emptyUsage),
        null,
    );
});

import assert from 'node:assert/strict';
import test from 'node:test';

import { filterModelChoices } from '../src/model-selection.js';

const choices = [
    {
        value: 'openrouter::deepseek/deepseek-v4-flash',
        label: 'DeepSeek: DeepSeek V4 Flash',
        provider: 'OpenRouter',
    },
    {
        value: 'openrouter::deepseek/deepseek-v4-flash-0731',
        label: 'DeepSeek: DeepSeek V4 Flash 0731',
        provider: 'OpenRouter',
    },
    {
        value: 'openrouter::openai/gpt-5.5',
        label: 'OpenAI: GPT-5.5',
        provider: 'OpenRouter',
    },
];

test('filters models by exact request ID, official name, and author terms', () => {
    assert.deepEqual(
        filterModelChoices(choices, '0731').map((choice) => choice.value),
        ['openrouter::deepseek/deepseek-v4-flash-0731'],
    );
    assert.equal(filterModelChoices(choices, 'deepseek flash').length, 2);
    assert.deepEqual(
        filterModelChoices(choices, 'openai gpt').map((choice) => choice.value),
        ['openrouter::openai/gpt-5.5'],
    );
});

test('returns all models for an empty query and none for a miss', () => {
    assert.equal(filterModelChoices(choices, '   '), choices);
    assert.deepEqual(filterModelChoices(choices, 'claude'), []);
});

import assert from 'node:assert/strict';
import test from 'node:test';

import { filterModelChoices, formatModelPanelLabel, modelPanelLabelWidth } from '../src/model-selection.js';

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

test('aligns model labels to the longest fetched model plus one space', () => {
    const fetchedModels = [
        { value: 'deepseek::pro', label: 'DeepSeek-V4-Pro', provider: 'DeepSeek' },
        { value: 'deepseek::flash', label: 'DeepSeek-V4-Flash', provider: 'DeepSeek' },
        {
            value: 'deepseek::vision',
            label: 'DeepSeek-V4-Flash-Vision-Exp',
            provider: 'DeepSeek',
        },
    ];

    const width = modelPanelLabelWidth(fetchedModels);
    assert.equal(width, 'DeepSeek-V4-Flash-Vision-Exp'.length + 1);
    assert.equal(
        formatModelPanelLabel(fetchedModels[0], width),
        `DeepSeek-V4-Pro${" ".repeat(width - 'DeepSeek-V4-Pro'.length)}`,
    );
    assert.equal(
        formatModelPanelLabel(fetchedModels[1], width),
        `DeepSeek-V4-Flash${" ".repeat(width - 'DeepSeek-V4-Flash'.length)}`,
    );
    assert.equal(
        formatModelPanelLabel(fetchedModels[2], width),
        'DeepSeek-V4-Flash-Vision-Exp ',
    );
});

test('keeps the model column width when filtering choices', () => {
    const fetchedModels = [
        { value: 'provider::short', label: 'Short', provider: 'Provider' },
        { value: 'provider::long', label: 'A-much-longer-model-name', provider: 'Provider' },
    ];
    const width = modelPanelLabelWidth(fetchedModels);
    const visibleModels = filterModelChoices(fetchedModels, 'short');

    assert.equal(
        formatModelPanelLabel(visibleModels[0], width),
        `Short${" ".repeat(width - 'Short'.length)}`,
    );
});

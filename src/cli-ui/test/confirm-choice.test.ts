import assert from 'node:assert/strict';

import {
    getSelectableConfirmChoices,
    getVisibleConfirmChoices,
    isCancelConfirmChoice,
    resolveConfirmChoiceDisplayIndex,
    resolveConfirmDecisionFromInput,
    resolveConfirmInputDecision,
} from '../src/confirm-choice.js';
import type { ConfirmChoice } from '../src/types.js';

const choices: ConfirmChoice[] = [
    { value: 'spotify_play', label: '🎧 Spotify 播放' },
    {
        value: 'remote_only',
        label: 'Clementine',
        disabled: true,
        disabled_reason: 'Remote control only',
    },
    { value: 'apple_music_play', label: '🍎 Apple Music 播放' },
    { value: 'online_play', label: '🌐 在线播放' },
    { value: 'cancel', label: '取消' },
];

assert.equal(resolveConfirmDecisionFromInput('online_play', choices), 'online_play');
assert.equal(resolveConfirmDecisionFromInput('在线播放', choices), 'online_play');
assert.equal(resolveConfirmDecisionFromInput('3', choices), 'online_play');
assert.equal(resolveConfirmDecisionFromInput('remote_only', choices), null);
assert.equal(resolveConfirmDecisionFromInput('Clementine', choices), null);
assert.equal(resolveConfirmDecisionFromInput('取消', choices), null);
assert.equal(resolveConfirmDecisionFromInput('unknown', choices), null);

assert.equal(isCancelConfirmChoice({ value: 'deny', label: 'Cancel' }), true);
assert.equal(isCancelConfirmChoice({ value: 'cancel', label: '取消' }), true);
assert.equal(isCancelConfirmChoice({ value: 'online_play', label: '🌐 在线播放' }), false);
assert.deepEqual(getVisibleConfirmChoices(choices).map((choice) => choice.value), [
    'spotify_play',
    'remote_only',
    'apple_music_play',
    'online_play',
]);
assert.deepEqual(getVisibleConfirmChoices(choices, true).map((choice) => choice.value), [
    'spotify_play',
    'remote_only',
    'apple_music_play',
    'online_play',
    'cancel',
]);
assert.deepEqual(getSelectableConfirmChoices(choices).map((choice) => choice.value), [
    'spotify_play',
    'apple_music_play',
    'online_play',
]);
assert.deepEqual(getSelectableConfirmChoices(choices, true).map((choice) => choice.value), [
    'spotify_play',
    'apple_music_play',
    'online_play',
    'cancel',
]);
assert.equal(resolveConfirmChoiceDisplayIndex(choices, 0), 0);
assert.equal(resolveConfirmChoiceDisplayIndex(choices, 1), 2);
assert.equal(resolveConfirmChoiceDisplayIndex(choices, 2), 3);
assert.equal(
    resolveConfirmChoiceDisplayIndex([
        { value: 'remote_only', label: 'Remote', disabled: true },
        { value: 'deny', label: 'Cancel' },
    ], 0),
    -1,
);
assert.equal(
    resolveConfirmChoiceDisplayIndex([
        { value: 'confirm_exit', label: 'Yes, I insist' },
        { value: 'deny', label: 'No, return' },
    ], 1, true),
    1,
);

assert.equal(
    resolveConfirmInputDecision(' live:acoustic ', { value: 'refine_query', label: '没有想听的歌曲', input: { placeholder: '试试补充更多信息' } }),
    'refine_query:live%3Aacoustic',
);
assert.equal(resolveConfirmInputDecision('', { value: 'refine_query', label: '没有想听的歌曲', input: { placeholder: '试试补充更多信息' } }), null);
assert.equal(resolveConfirmInputDecision('live', { value: 'online_play', label: '在线播放' }), null);

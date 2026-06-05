import assert from 'node:assert/strict';

import {resolveConfirmDecisionFromInput} from '../src/confirm-choice.js';
import type {ConfirmChoice} from '../src/types.js';

const choices: ConfirmChoice[] = [
    {value: 'spotify_play', label: '🎧 Spotify 播放'},
    {value: 'apple_music_play', label: '🍎 Apple Music 播放'},
    {value: 'online_play', label: '🌐 在线播放'},
    {value: 'cancel', label: '取消'},
];

assert.equal(resolveConfirmDecisionFromInput('online_play', choices), 'online_play');
assert.equal(resolveConfirmDecisionFromInput('在线播放', choices), 'online_play');
assert.equal(resolveConfirmDecisionFromInput('3', choices), 'online_play');
assert.equal(resolveConfirmDecisionFromInput('取消', choices), 'cancel');
assert.equal(resolveConfirmDecisionFromInput('unknown', choices), null);

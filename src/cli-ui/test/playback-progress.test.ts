import assert from 'node:assert/strict';

import {PLAYBACK_PROGRESS_INTERVAL_MS, playbackProgressAt, shouldUsePlaybackProgressTimer} from '../src/hooks.js';

assert.equal(PLAYBACK_PROGRESS_INTERVAL_MS, 1000);
assert.equal(playbackProgressAt({
    name: "Song",
    artist: "Artist",
    album: "-",
    duration_ms: 10000,
    progress_ms: 1000,
    timestamp: 1000,
    is_playing: true,
}, 1250), 1250);
assert.equal(playbackProgressAt({
    name: "Song",
    artist: "Artist",
    album: "-",
    duration_ms: 10000,
    progress_ms: 1000,
    timestamp: 1000,
    is_playing: false,
}, 2000), 1000);
assert.equal(playbackProgressAt({
    name: "Song",
    artist: "Artist",
    album: "-",
    duration_ms: 1200,
    progress_ms: 1000,
    timestamp: 1000,
    is_playing: true,
}, 2000), 1200);
assert.equal(shouldUsePlaybackProgressTimer({
    name: "Song",
    artist: "Artist",
    album: "-",
    duration_ms: 10000,
    progress_ms: 1000,
    is_playing: true,
}, false), false);
assert.equal(shouldUsePlaybackProgressTimer({
    name: "Song",
    artist: "Artist",
    album: "-",
    duration_ms: 10000,
    progress_ms: 1000,
    is_playing: true,
}, true), true);

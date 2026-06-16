import assert from 'node:assert/strict';

import {
    clampPlaybackVolume,
    isLocalPlaybackShortcutSource,
    playbackCommandForShortcut,
    playbackShortcutFromInput,
} from '../src/playback-keymap.js';

assert.equal(playbackShortcutFromInput(" "), "togglePlayback");
assert.equal(playbackShortcutFromInput("\x1b[19~"), "volumeDown");
assert.equal(playbackShortcutFromInput("\x1b[20~"), "volumeUp");
assert.equal(playbackShortcutFromInput("\x13"), "saveToPlaylist");
assert.equal(playbackShortcutFromInput("\t"), null);
assert.equal(playbackShortcutFromInput("x"), null);

assert.equal(clampPlaybackVolume(100, 5), 100);
assert.equal(clampPlaybackVolume(98, 5), 100);
assert.equal(clampPlaybackVolume(2, -5), 0);
assert.equal(clampPlaybackVolume(null, -5), 95);
assert.equal(clampPlaybackVolume(undefined, 5), 100);

assert.equal(playbackCommandForShortcut("togglePlayback", { is_playing: true }), "/pause");
assert.equal(playbackCommandForShortcut("togglePlayback", { is_playing: false }), "/resume");
assert.equal(playbackCommandForShortcut("volumeDown", { volume_percent: 44 }), "/volume 39");
assert.equal(playbackCommandForShortcut("volumeUp", { volume_percent: 98 }), "/volume 100");
assert.equal(playbackCommandForShortcut("saveToPlaylist", { is_playing: true }), "/playlist save");

assert.equal(isLocalPlaybackShortcutSource({ source: "youtube", provider: "youtube" }), true);
assert.equal(isLocalPlaybackShortcutSource({ source: "spotify", provider: "spotify" }), false);

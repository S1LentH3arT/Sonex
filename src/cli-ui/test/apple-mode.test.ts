import assert from 'node:assert/strict';
import test from 'node:test';

import { appleModeSlashCommands } from '../src/commands.js';
import { resolveRegionAfterPlayerEvent, toggleShellRegion } from '../src/layout.js';
import { isApplePlaybackShortcutSource } from '../src/playback-keymap.js';

test('Apple Mode slash menu exposes provider switching and exit command', () => {
    const names = appleModeSlashCommands('/').map(command => command.name);
    assert.ok(names.includes('apple'));
    assert.ok(names.includes('spotify'));
    assert.ok(names.includes('queue'));
    assert.ok(!names.includes('playlist'));
});

test('Apple player event opens the generic provider immersive region', () => {
    const transition = resolveRegionAfterPlayerEvent({
        currentRegion: 'chat',
        wasSessionActive: false,
        player: {
            name: '特別的人',
            artist: '方大同',
            album: '危險世界',
            duration_ms: 240000,
            is_playing: true,
            provider: 'apple_music',
        },
        providerMode: 'apple',
    });
    assert.equal(transition.region, 'providerImmersive');
    assert.equal(transition.sessionActive, true);
});

test('Tab toggles between chat and the generic provider region', () => {
    assert.equal(toggleShellRegion('chat', true, false, true), 'providerImmersive');
    assert.equal(toggleShellRegion('providerImmersive', true, false, true), 'chat');
});

test('Apple Music is an external provider shortcut source', () => {
    assert.equal(isApplePlaybackShortcutSource({ source: 'apple_music' }), true);
    assert.equal(isApplePlaybackShortcutSource({ provider: 'spotify' }), false);
});

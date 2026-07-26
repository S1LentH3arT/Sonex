import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
    resolveChatHeaderVariant,
    resolveMiniPlayerLayout,
    resolveSpotifyImmersiveLayout,
    hasActivePlaybackSession,
    resolveRegionAfterPlayerEvent,
    toggleShellRegion,
} from '../src/layout.js';
import type { PlayerState } from '../src/types.js';

const layoutSource = readFileSync(new URL('../src/layout.ts', import.meta.url), 'utf8');

assert.match(
    layoutSource,
    /export type ShellRegion = 'chat' \| 'miniPlayer' \| 'spotifyImmersive' \| 'trackPanel';/,
);

const idle: PlayerState = {
    name: '-',
    artist: '-',
    album: '-',
    duration_ms: 0,
    progress_ms: 0,
    is_playing: false,
};

const playing: PlayerState = {
    name: 'Track',
    artist: 'Artist',
    album: 'Album',
    duration_ms: 120_000,
    progress_ms: 1_000,
    is_playing: true,
    session_id: 'session-1',
    ended: false,
};

assert.equal(hasActivePlaybackSession(idle, false), false);
assert.equal(hasActivePlaybackSession(playing, false), true);
assert.equal(hasActivePlaybackSession({ ...playing, is_playing: false }, true), true);
assert.equal(hasActivePlaybackSession({ ...playing, is_playing: false, ended: true }, true), false);
assert.equal(hasActivePlaybackSession(idle, true), false);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'chat',
        wasSessionActive: false,
        player: playing,
    }),
    { region: 'miniPlayer', sessionActive: true },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'chat',
        wasSessionActive: false,
        player: { ...playing, provider: 'spotify', source: 'spotify' },
        spotifyModeEnabled: true,
    }),
    { region: 'spotifyImmersive', sessionActive: true },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'chat',
        wasSessionActive: false,
        player: playing,
        spotifyModeEnabled: true,
    }),
    { region: 'spotifyImmersive', sessionActive: true },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'chat',
        wasSessionActive: false,
        player: { ...playing, source: 'local' },
        spotifyModeEnabled: true,
    }),
    { region: 'spotifyImmersive', sessionActive: true },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'spotifyImmersive',
        wasSessionActive: true,
        player: { ...playing, is_playing: false, provider: 'spotify', source: 'spotify' },
        spotifyModeEnabled: true,
    }),
    { region: 'spotifyImmersive', sessionActive: true },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'chat',
        wasSessionActive: true,
        player: { ...playing, progress_ms: 2_000, provider: 'spotify', source: 'spotify' },
        spotifyModeEnabled: true,
    }),
    { region: 'chat', sessionActive: true },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'chat',
        wasSessionActive: true,
        player: { ...playing, is_playing: false, provider: 'spotify', source: 'spotify' },
        spotifyModeEnabled: true,
    }),
    { region: 'chat', sessionActive: true },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'chat',
        wasSessionActive: true,
        player: { ...playing, name: 'Next Track', provider: 'spotify', source: 'spotify' },
        spotifyModeEnabled: true,
    }),
    { region: 'chat', sessionActive: true },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'miniPlayer',
        wasSessionActive: true,
        player: { ...playing, is_playing: false },
    }),
    { region: 'miniPlayer', sessionActive: true },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'chat',
        wasSessionActive: true,
        player: { ...playing, is_playing: true, name: 'Next Track' },
    }),
    { region: 'chat', sessionActive: true },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'miniPlayer',
        wasSessionActive: true,
        player: { ...playing, is_playing: false, ended: true },
    }),
    { region: 'chat', sessionActive: false },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'miniPlayer',
        wasSessionActive: true,
        player: idle,
    }),
    { region: 'chat', sessionActive: false },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'trackPanel',
        wasSessionActive: true,
        player: { ...playing, is_playing: false },
    }),
    { region: 'trackPanel', sessionActive: true },
);

assert.deepEqual(
    resolveRegionAfterPlayerEvent({
        currentRegion: 'trackPanel',
        wasSessionActive: true,
        player: { ...playing, is_playing: false, ended: true },
    }),
    { region: 'chat', sessionActive: false },
);

assert.equal(toggleShellRegion('chat', true), 'miniPlayer');
assert.equal(toggleShellRegion('chat', true, true), 'spotifyImmersive');
assert.equal(toggleShellRegion('miniPlayer', true), 'chat');
assert.equal(toggleShellRegion('spotifyImmersive', true), 'chat');
assert.equal(toggleShellRegion('trackPanel', true), 'chat');
assert.equal(toggleShellRegion('chat', false), 'chat');
assert.equal(toggleShellRegion('chat', false, true), 'chat');
assert.equal(toggleShellRegion('miniPlayer', false), 'chat');
assert.equal(toggleShellRegion('spotifyImmersive', false), 'chat');
assert.equal(toggleShellRegion('trackPanel', false), 'chat');

assert.equal(resolveChatHeaderVariant(71), 'compact');
assert.equal(resolveChatHeaderVariant(72), 'full');

const artwork = resolveMiniPlayerLayout({ columns: 124, rows: 44 });
assert.equal(artwork.mode, 'artwork');
assert.equal(artwork.contentColumns, 124);
assert.equal(artwork.contentRows, 44);
assert.equal(artwork.infoWidth, 40);
assert.equal(artwork.infoLeftPadding, 4);
assert.equal(artwork.gap, 1);
assert.equal(artwork.coverWidth, 83);
assert.equal(artwork.infoTop, 20);
assert.deepEqual(artwork.progressSlot, {
    row: 23,
    column: 5,
    width: 36,
});
assert.deepEqual(artwork.statusIconSlot, {
    row: 24,
    column: 5,
    width: 36,
});

const exactMinimumArtwork = resolveMiniPlayerLayout({ columns: 57, rows: 16 });
assert.equal(exactMinimumArtwork.mode, 'artwork');
assert.equal(exactMinimumArtwork.coverWidth, 32);

const targetArtwork = resolveMiniPlayerLayout({ columns: 105, rows: 40 });
assert.equal(targetArtwork.mode, 'artwork');
assert.equal(targetArtwork.infoWidth, 24);
assert.equal(targetArtwork.coverWidth, 80);

const spotifyImmersive = resolveSpotifyImmersiveLayout({ columns: 100, rows: 30 });
assert.equal(spotifyImmersive.topPadding, 10);
assert.deepEqual(spotifyImmersive.progressSlot, {
    row: 16,
    column: 27,
    width: 48,
});
assert.deepEqual(spotifyImmersive.deviceSlot, {
    row: 17,
    column: 27,
    width: 48,
});

const narrowArtwork = resolveMiniPlayerLayout({ columns: 100, rows: 40 });
assert.equal(narrowArtwork.mode, 'artwork');
assert.equal(narrowArtwork.infoWidth, 24);
assert.equal(narrowArtwork.coverWidth, 75);

const infoOnly = resolveMiniPlayerLayout({ columns: 56, rows: 16 });
assert.equal(infoOnly.mode, 'infoOnly');
assert.equal(infoOnly.infoWidth, 56);
assert.equal(infoOnly.infoLeftPadding, 0);
assert.equal(infoOnly.coverWidth, 0);
assert.equal(infoOnly.gap, 0);

const tooShortForArtwork = resolveMiniPlayerLayout({ columns: 124, rows: 15 });
assert.equal(tooShortForArtwork.mode, 'infoOnly');
assert.equal(tooShortForArtwork.coverWidth, 0);

const tinyTerminal = resolveMiniPlayerLayout({ columns: 40, rows: 2 });
assert.equal(tinyTerminal.progressSlot.row, 1);
assert.equal(tinyTerminal.statusIconSlot.row, 1);
assert.ok(tinyTerminal.progressSlot.width >= 0);
assert.ok(tinyTerminal.statusIconSlot.width >= 0);
assert.ok(tinyTerminal.infoWidth >= 0);

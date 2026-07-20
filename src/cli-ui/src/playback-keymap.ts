import type { PlayerState } from './types.js';

export type PlaybackShortcutAction = "togglePlayback" | "volumeDown" | "volumeUp" | "saveToPlaylist";

const LOCAL_PLAYBACK_SOURCES = new Set(["local", "youtube", "online"]);
const EXTERNAL_PLAYBACK_SOURCES = new Set(["spotify", "apple_music"]);

/**
 * Maps raw terminal input bytes to mini-player playback shortcut actions.
 */
export function playbackShortcutFromInput(input: string): PlaybackShortcutAction | null {
    if (input === " ") return "togglePlayback";
    if (input === "\x1b[19~") return "volumeDown";
    if (input === "\x1b[20~") return "volumeUp";
    if (input === "\x13") return "saveToPlaylist";
    return null;
}

/**
 * Clamps a playback volume adjustment to the local player range.
 */
export function clampPlaybackVolume(currentVolume: number | null | undefined, delta: number): number {
    const current = typeof currentVolume === "number" && Number.isFinite(currentVolume)
        ? currentVolume
        : 100;
    return Math.min(100, Math.max(0, current + delta));
}

/**
 * Builds the existing local playback command for a parsed shortcut action.
 */
export function playbackCommandForShortcut(
    action: PlaybackShortcutAction,
    player: Pick<PlayerState, "is_playing" | "volume_percent">,
): string {
    if (action === "togglePlayback") {
        return player.is_playing === true ? "/pause" : "/resume";
    }
    if (action === "saveToPlaylist") {
        return "/playlist save";
    }
    const delta = action === "volumeDown" ? -5 : 5;
    return `/volume ${clampPlaybackVolume(player.volume_percent, delta)}`;
}

/**
 * Returns whether the active player state belongs to local/online playback.
 */
export function isLocalPlaybackShortcutSource(player: Pick<PlayerState, "source" | "provider">): boolean {
    const source = typeof player.source === "string" ? player.source.toLowerCase() : "";
    const provider = typeof player.provider === "string" ? player.provider.toLowerCase() : "";
    if (EXTERNAL_PLAYBACK_SOURCES.has(source) || EXTERNAL_PLAYBACK_SOURCES.has(provider)) {
        return false;
    }
    if (!source && !provider) return true;
    return LOCAL_PLAYBACK_SOURCES.has(source) || LOCAL_PLAYBACK_SOURCES.has(provider);
}

/**
 * Returns whether the active player state belongs to Spotify playback.
 */
export function isSpotifyPlaybackShortcutSource(player: Pick<PlayerState, "source" | "provider">): boolean {
    const source = typeof player.source === "string" ? player.source.toLowerCase() : "";
    const provider = typeof player.provider === "string" ? player.provider.toLowerCase() : "";
    return source === "spotify" || provider === "spotify";
}

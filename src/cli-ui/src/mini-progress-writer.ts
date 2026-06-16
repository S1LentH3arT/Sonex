import React from 'react';
import { buildProgressBar, formatDuration } from './format.js';
import { playbackProgressAt, PLAYBACK_PROGRESS_INTERVAL_MS } from './hooks.js';
import type { TerminalLinePosition } from './layout.js';
import type { PlayerState } from './types.js';

export type TerminalWriter = {
    write(chunk: string): unknown;
};

export type PlaybackProgressUpdateMode = 'off' | 'once' | 'interval';
export type MiniSnapshotRefreshReason = 'region' | 'resize' | 'player' | 'cover';

const PLAYING_STATUS_ICON = '▶ ';
const PAUSED_STATUS_ICON = '▌▌';

export function resolvePlaybackProgressUpdateMode(enabled: boolean, player: PlayerState): PlaybackProgressUpdateMode {
    if (!enabled || player.ended === true) return 'off';
    return player.is_playing === true ? 'interval' : 'once';
}

export function shouldRefreshMiniSnapshot(reason: MiniSnapshotRefreshReason): boolean {
    return reason === 'region' || reason === 'resize';
}

export function buildPlaybackProgressLine(player: PlayerState, now: number, width: number): string {
    const progressMs = playbackProgressAt(player, now);
    const progress = formatDuration(progressMs);
    const duration = formatDuration(player.duration_ms);
    const barWidth = Math.max(6, width - progress.length - duration.length - 2);
    const progressBar = buildProgressBar(progressMs, player.duration_ms, barWidth);
    return `${progress} ${progressBar} ${duration}`;
}

export function buildPlaybackStatusIconLine(player: PlayerState, width: number): string {
    const icon = player.is_playing === true ? PLAYING_STATUS_ICON : PAUSED_STATUS_ICON;
    if (width <= icon.length) return icon.slice(0, Math.max(0, width));
    const leftPadding = Math.floor((width - icon.length) / 2);
    return `${' '.repeat(leftPadding)}${icon}`;
}

export function writeTerminalLine(stdout: TerminalWriter, position: TerminalLinePosition, text: string): void {
    if (position.width <= 0) return;
    const padded = text.slice(0, position.width).padEnd(position.width, ' ');
    stdout.write(`\u001B7\u001B[${position.row};${position.column}H${padded}\u001B8`);
}

export function usePlaybackProgressWriter({
    enabled,
    player,
    position,
    stdout,
}: {
    enabled: boolean;
    player: PlayerState;
    position: TerminalLinePosition;
    stdout: TerminalWriter;
}): void {
    const playerRef = React.useRef(player);
    playerRef.current = player;

    const writeProgress = React.useCallback(() => {
        writeTerminalLine(stdout, position, buildPlaybackProgressLine(playerRef.current, Date.now(), position.width));
    }, [position.column, position.row, position.width, stdout]);
    const updateMode = resolvePlaybackProgressUpdateMode(enabled, player);

    React.useEffect(() => {
        if (updateMode === 'off') return;
        writeProgress();
        if (updateMode === 'once') return;
        const timer = setInterval(writeProgress, PLAYBACK_PROGRESS_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [player, updateMode, writeProgress]);
}

export function usePlaybackStatusIconWriter({
    enabled,
    player,
    position,
    stdout,
}: {
    enabled: boolean;
    player: PlayerState;
    position: TerminalLinePosition;
    stdout: TerminalWriter;
}): void {
    React.useEffect(() => {
        if (!enabled) return;
        writeTerminalLine(stdout, position, buildPlaybackStatusIconLine(player, position.width));
    }, [enabled, player.is_playing, position.column, position.row, position.width, stdout]);
}

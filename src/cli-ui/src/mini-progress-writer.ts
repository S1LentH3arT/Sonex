import React from 'react';
import { buildProgressBar, formatDuration } from './format.js';
import { playbackProgressAt, PLAYBACK_PROGRESS_INTERVAL_MS } from './hooks.js';
import type { TerminalLinePosition } from './layout.js';
import type { PlayerState } from './types.js';

export type TerminalWriter = {
    write(chunk: string): unknown;
};

export type MiniProgressUpdateMode = 'off' | 'once' | 'interval';
export type MiniSnapshotRefreshReason = 'region' | 'resize' | 'player' | 'cover';

export function resolveMiniProgressUpdateMode(enabled: boolean, player: PlayerState): MiniProgressUpdateMode {
    if (!enabled || player.ended === true) return 'off';
    return player.is_playing === true ? 'interval' : 'once';
}

export function shouldRefreshMiniSnapshot(reason: MiniSnapshotRefreshReason): boolean {
    return reason === 'region' || reason === 'resize';
}

export function buildMiniProgressLine(player: PlayerState, now: number, width: number): string {
    const progressMs = playbackProgressAt(player, now);
    const progress = formatDuration(progressMs);
    const duration = formatDuration(player.duration_ms);
    const barWidth = Math.max(6, width - progress.length - duration.length - 2);
    const progressBar = buildProgressBar(progressMs, player.duration_ms, barWidth);
    return `${progress} ${progressBar} ${duration}`;
}

export function writeTerminalLine(stdout: TerminalWriter, position: TerminalLinePosition, text: string): void {
    if (position.width <= 0) return;
    const padded = text.slice(0, position.width).padEnd(position.width, ' ');
    stdout.write(`\u001B7\u001B[${position.row};${position.column}H${padded}\u001B8`);
}

export function useMiniProgressWriter({
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
        writeTerminalLine(stdout, position, buildMiniProgressLine(playerRef.current, Date.now(), position.width));
    }, [position.column, position.row, position.width, stdout]);
    const updateMode = resolveMiniProgressUpdateMode(enabled, player);

    React.useEffect(() => {
        if (updateMode === 'off') return;
        writeProgress();
        if (updateMode === 'once') return;
        const timer = setInterval(writeProgress, PLAYBACK_PROGRESS_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [player, updateMode, writeProgress]);
}

import React from 'react';
import { buildProgressBar, formatDuration } from './format.js';
import { playbackProgressAt, PLAYBACK_PROGRESS_INTERVAL_MS } from './hooks.js';
import type { TerminalSize } from './layout.js';
import type { PlayerState } from './types.js';

/**
 * Describes the terminal writer type.
 *
 * Documents the shape shared across mini-progress.ts call sites.
 */
export type TerminalWriter = {
    write(chunk: string): unknown;
};

/**
 * Describes the terminal line position type.
 *
 * Documents the shape shared across mini-progress.ts call sites.
 */
export type TerminalLinePosition = {
    row: number;
    column: number;
    width: number;
};

/**
 * Build mini progress line.
 *
 * Coordinates the build mini progress line operation for the CLI UI runtime.
 *
 * @param player Input value used by the build mini progress line operation.
 * @param now Input value used by the build mini progress line operation.
 * @param width Input value used by the build mini progress line operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function buildMiniProgressLine(player: PlayerState, now: number, width: number): string {
    /**
     * Defines the progress constant.
     *
     * Stores stable configuration or display data consumed by mini-progress.ts.
     */
    const progress = formatDuration(playbackProgressAt(player, now));
    /**
     * Defines the duration constant.
     *
     * Stores stable configuration or display data consumed by mini-progress.ts.
     */
    const duration = formatDuration(player.duration_ms);
    /**
     * Defines the bar width constant.
     *
     * Stores stable configuration or display data consumed by mini-progress.ts.
     */
    const barWidth = Math.max(6, width - progress.length - duration.length - 2);
    /**
     * Defines the progress bar constant.
     *
     * Stores stable configuration or display data consumed by mini-progress.ts.
     */
    const progressBar = buildProgressBar(playbackProgressAt(player, now), player.duration_ms, barWidth);
    return `${progress} ${progressBar} ${duration}`;
}

/**
 * Resolve mini progress position.
 *
 * Coordinates the resolve mini progress position operation for the CLI UI runtime.
 *
 * @param size Input value used by the resolve mini progress position operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function resolveMiniProgressPosition(size: TerminalSize): TerminalLinePosition | null {
    if (!size.columns || !size.rows || size.columns < 18 || size.rows < 6) {
        return null;
    }

    return {
        row: Math.max(1, size.rows - 2),
        column: 3,
        width: Math.max(6, size.columns - 6),
    };
}

/**
 * Write terminal line.
 *
 * Coordinates the write terminal line operation for the CLI UI runtime.
 *
 * @param stdout Input value used by the write terminal line operation.
 * @param position Input value used by the write terminal line operation.
 * @param text Input value used by the write terminal line operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function writeTerminalLine(stdout: TerminalWriter, position: TerminalLinePosition, text: string): void {
    /**
     * Defines the padded constant.
     *
     * Stores stable configuration or display data consumed by mini-progress.ts.
     */
    const padded = text.slice(0, position.width).padEnd(position.width, ' ');
    stdout.write(`\u001B7\u001B[${position.row};${position.column}H\u001B[2K${padded}\u001B8`);
}

/**
 * Use mini progress writer.
 *
 * Coordinates the use mini progress writer operation for the CLI UI runtime.
 *
 * @param enabled,player,terminalSize,stdout, Input value used by the use mini progress writer operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function useMiniProgressWriter({
    enabled,
    player,
    terminalSize,
    stdout,
}: {
    enabled: boolean;
    player: PlayerState;
    terminalSize: TerminalSize;
    stdout: TerminalWriter;
}): void {
    /**
     * Defines the player ref constant.
     *
     * Stores stable configuration or display data consumed by mini-progress.ts.
     */
    const playerRef = React.useRef(player);
    playerRef.current = player;

    /**
     * Defines the write progress constant.
     *
     * Stores stable configuration or display data consumed by mini-progress.ts.
     */
    const writeProgress = React.useCallback(() => {
        /**
         * Defines the position constant.
         *
         * Stores stable configuration or display data consumed by mini-progress.ts.
         */
        const position = resolveMiniProgressPosition(terminalSize);
        if (!position) return;
        writeTerminalLine(stdout, position, buildMiniProgressLine(playerRef.current, Date.now(), position.width));
    }, [stdout, terminalSize.columns, terminalSize.rows]);

    React.useEffect(() => {
        if (!enabled || player.is_playing !== true) return;
        writeProgress();
    }, [enabled, player, writeProgress]);

    React.useEffect(() => {
        if (!enabled || player.is_playing !== true) return;
        writeProgress();
        /**
         * Defines the timer constant.
         *
         * Stores stable configuration or display data consumed by mini-progress.ts.
         */
        const timer = setInterval(writeProgress, PLAYBACK_PROGRESS_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [enabled, player.is_playing, writeProgress]);
}

import React from 'react';
import { buildProgressBar, formatDuration } from './format.js';
import { isPlaybackStarting, playbackProgressAt, PLAYBACK_PROGRESS_INTERVAL_MS } from './hooks.js';
import type { TerminalLinePosition } from './layout.js';
import type { PlayerState } from './types.js';

export type TerminalWriter = {
    write(chunk: string): unknown;
};

export type PlaybackProgressUpdateMode = 'off' | 'once' | 'interval';
export type MiniSnapshotRefreshReason = 'region' | 'resize' | 'player' | 'cover';

const PLAYING_STATUS_ICON = '▶ ';
const PAUSED_STATUS_ICON = '▌▌';
const LIKED_HEART = '⣠⣶⣄';
const UNLIKED_HEART = '⣠ ⣄';
const ANSI_RED = '\u001B[31m';
const ANSI_RESET_FG = '\u001B[39m';

export type TerminalLineSegment = {
    text: string;
    color?: 'red';
};

export type TerminalLine = {
    text: string;
    segments: TerminalLineSegment[];
};

export function resolvePlaybackProgressUpdateMode(enabled: boolean, player: PlayerState): PlaybackProgressUpdateMode {
    if (!enabled || player.ended === true) return 'off';
    if (isPlaybackStarting(player)) return 'once';
    return player.is_playing === true ? 'interval' : 'once';
}

export function shouldRefreshMiniSnapshot(reason: MiniSnapshotRefreshReason): boolean {
    return reason === 'region' || reason === 'resize';
}

export function buildPlaybackProgressLine(player: PlayerState, now: number, width: number): string {
    const progressMs = playbackProgressAt(player, now);
    const progress = isPlaybackStarting(player) ? 'starting' : formatDuration(progressMs);
    const duration = formatDuration(player.duration_ms);
    const barWidth = Math.max(6, width - progress.length - duration.length - 2);
    const progressBar = buildProgressBar(progressMs, player.duration_ms, barWidth);
    return `${progress} ${progressBar} ${duration}`;
}

export function playbackStatusIconSegments(player: PlayerState): TerminalLineSegment[] {
    const icon = player.is_playing === true ? PLAYING_STATUS_ICON : PAUSED_STATUS_ICON;
    return [
        { text: icon },
        { text: ' ' },
        { text: player.is_liked === true ? LIKED_HEART : UNLIKED_HEART, color: player.is_liked === true ? 'red' : undefined },
    ];
}

function visibleText(segments: TerminalLineSegment[]): string {
    return segments.map((segment) => segment.text).join('');
}

function sliceVisible(text: string, width: number): string {
    return Array.from(text).slice(0, Math.max(0, width)).join('');
}

export function buildPlaybackStatusIconLine(player: PlayerState, width: number): TerminalLine {
    const icon = player.is_playing === true ? PLAYING_STATUS_ICON : PAUSED_STATUS_ICON;
    if (width <= icon.length) {
        const trimmedIcon = icon.slice(0, Math.max(0, width));
        return { text: trimmedIcon, segments: [{ text: trimmedIcon }] };
    }
    const segments = playbackStatusIconSegments(player);
    const text = visibleText(segments);
    if (width <= text.length) {
        const trimmed = sliceVisible(text, width);
        return { text: trimmed, segments: [{ text: trimmed }] };
    }
    const leftPadding = Math.floor((width - text.length) / 2);
    const paddedSegments = leftPadding > 0 ? [{ text: ' '.repeat(leftPadding) }, ...segments] : segments;
    return { text: `${' '.repeat(leftPadding)}${text}`, segments: paddedSegments };
}

function renderTerminalLine(line: string | TerminalLine): string {
    if (typeof line === 'string') return line;
    return line.segments.map((segment) => {
        if (segment.color === 'red') return `${ANSI_RED}${segment.text}${ANSI_RESET_FG}`;
        return segment.text;
    }).join('');
}

export function writeTerminalLine(stdout: TerminalWriter, position: TerminalLinePosition, line: string | TerminalLine): void {
    if (position.width <= 0) return;
    const text = typeof line === 'string' ? line : line.text;
    const visible = sliceVisible(text, position.width);
    const rendered = renderTerminalLine(line);
    const padded = `${rendered}${' '.repeat(Math.max(0, position.width - visible.length))}`;
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
    }, [enabled, player.is_liked, player.is_playing, position.column, position.row, position.width, stdout]);
}

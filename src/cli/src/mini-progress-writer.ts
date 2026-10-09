import React from 'react';
import { buildProgressBar, formatDuration } from './format.js';
import { isPlaybackProgressFrozen, isPlaybackStarting, playbackProgressAt, PLAYBACK_PROGRESS_INTERVAL_MS } from './hooks.js';
import type { TerminalLinePosition } from './layout.js';
import type { PlayerState } from './types.js';

export type TerminalWriter = {
    write(chunk: string): unknown;
};

export type PlaybackProgressUpdateMode = 'off' | 'once' | 'interval';
export type MiniSnapshotRefreshReason = 'region' | 'resize' | 'player' | 'cover';

const PLAYING_STATUS_ICON = '▶';
const PAUSED_STATUS_ICON = '▌▌';
const SAVED_PLAYLIST_ICON = '✔';
const ADD_TO_PLAYLIST_ICON = '+';
const ANSI_GREEN = '\u001B[32m';
const ANSI_RESET_FG = '\u001B[39m';

export type TerminalLineSegment = {
    text: string;
    color?: 'green';
};

export type TerminalLine = {
    text: string;
    segments: TerminalLineSegment[];
};

export function resolvePlaybackProgressUpdateMode(enabled: boolean, player: PlayerState): PlaybackProgressUpdateMode {
    if (!enabled || player.ended === true) return 'off';
    if (isPlaybackProgressFrozen(player)) return 'once';
    return player.is_playing === true ? 'interval' : 'once';
}

export function shouldRefreshMiniSnapshot(reason: MiniSnapshotRefreshReason): boolean {
    return reason === 'region' || reason === 'resize';
}

function playbackProgressLabel(player: PlayerState, progressMs: number): string {
    if (isPlaybackStarting(player)) return 'starting';
    if (player.progress_sync_lost === true) return 'syncing';
    if (player.paused_for_cache === true) return 'buffering';
    if (player.diagnostic_notice) return 'diagnostic';
    return formatDuration(progressMs);
}

function playbackProgressLayout(player: PlayerState, now: number, width: number): {
    progress: string;
    duration: string;
    barWidth: number;
    barStart: number;
} {
    const progress = playbackProgressLabel(player, playbackProgressAt(player, now));
    const duration = formatDuration(player.duration_ms);
    const barWidth = Math.max(6, width - progress.length - duration.length - 2);
    return {
        progress,
        duration,
        barWidth,
        barStart: progress.length + 1,
    };
}

export function buildPlaybackProgressLine(player: PlayerState, now: number, width: number): string {
    const progressMs = playbackProgressAt(player, now);
    const layout = playbackProgressLayout(player, now, width);
    const progressBar = buildProgressBar(progressMs, player.duration_ms, layout.barWidth);
    return `${layout.progress} ${progressBar} ${layout.duration}`;
}

export function playbackStatusIconSegments(player: PlayerState, width: number, now: number): TerminalLineSegment[] {
    const playbackIcon = player.is_playing === true ? PLAYING_STATUS_ICON : PAUSED_STATUS_ICON;
    const progressLayout = playbackProgressLayout(player, now, width);
    const centeredStart = progressLayout.barStart + Math.floor((progressLayout.barWidth - playbackIcon.length) / 2);
    const playbackStart = Math.max(0, Math.min(centeredStart, Math.max(0, width - playbackIcon.length)));
    const visiblePlaybackIcon = sliceVisible(playbackIcon, Math.max(0, width - playbackStart));
    const segments: TerminalLineSegment[] = [];
    if (playbackStart > 0) segments.push({ text: ' '.repeat(playbackStart) });
    if (visiblePlaybackIcon) segments.push({ text: visiblePlaybackIcon });

    const playlistIcon = player.is_in_playlist === true ? SAVED_PLAYLIST_ICON : ADD_TO_PLAYLIST_ICON;
    const remainingWidth = width - playbackStart - visiblePlaybackIcon.length;
    if (remainingWidth >= playlistIcon.length + 1) {
        segments.push({ text: ' ' });
        segments.push({
            text: playlistIcon,
            color: player.is_in_playlist === true ? 'green' : undefined,
        });
    }
    return segments;
}

function visibleText(segments: TerminalLineSegment[]): string {
    return segments.map((segment) => segment.text).join('');
}

function sliceVisible(text: string, width: number): string {
    return Array.from(text).slice(0, Math.max(0, width)).join('');
}

export function buildPlaybackStatusIconLine(player: PlayerState, width: number, now: number = Date.now()): TerminalLine {
    const segments = playbackStatusIconSegments(player, width, now);
    const text = visibleText(segments);
    return { text, segments };
}

function renderTerminalLine(line: string | TerminalLine): string {
    if (typeof line === 'string') return line;
    return line.segments.map((segment) => {
        if (segment.color === 'green') return `${ANSI_GREEN}${segment.text}${ANSI_RESET_FG}`;
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
        writeTerminalLine(stdout, position, buildPlaybackStatusIconLine(player, position.width, Date.now()));
    }, [enabled, player.is_in_playlist, player.is_playing, player.playback_status, player.progress_ms, position.column, position.row, position.width, stdout]);
}

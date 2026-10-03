import React from 'react';
import WebSocket from 'ws';
import { API_NOT_RUNNING_DETAIL, API_NOT_RUNNING_MESSAGE } from './constants.js';
import type { ClientEvent, PlayerState, ServerEvent } from './types.js';

export const PLAYBACK_PROGRESS_INTERVAL_MS = 1000;

export function isPlaybackStarting(player: PlayerState): boolean {
    return player.playback_status === "starting";
}

export function isPlaybackProgressFrozen(player: PlayerState): boolean {
    return isPlaybackStarting(player)
        || player.progress_sync_lost === true
        || player.paused_for_cache === true;
}

/**
 * Coordinates the should use playback progress timer operation for the CLI UI runtime.
 *
 * @param player Input value used by the should use playback progress timer operation.
 * @param active Input value used by the should use playback progress timer operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function shouldUsePlaybackProgressTimer(player: PlayerState, active = true): boolean {
    return active
        && player.is_playing === true
        && !isPlaybackProgressFrozen(player);
}

/**
 * Coordinates the playback progress at operation for the CLI UI runtime.
 *
 * @param player Input value used by the playback progress at operation.
 * @param now Input value used by the playback progress at operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function playbackProgressAt(player: PlayerState, now: number): number {
    const base = player.progress_ms ?? 0;
    if (isPlaybackProgressFrozen(player)) return base;
    const reference = player.progress_anchor_ms ?? player.timestamp ?? player.started_at;
    const liveOffset = player.is_playing && reference ? Math.max(0, now - reference) : 0;
    const progress = base + liveOffset;
    return player.duration_ms > 0 ? Math.min(player.duration_ms, progress) : progress;
}

/**
 * Coordinates the use playback progress operation for the CLI UI runtime.
 *
 * @param player Input value used by the use playback progress operation.
 * @param active Input value used by the use playback progress operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function usePlaybackProgress(player: PlayerState, active = true): number {
    const [now, setNow] = React.useState(Date.now());

    React.useEffect(() => {
        if (!shouldUsePlaybackProgressTimer(player, active)) {
            setNow(Date.now());
            return;
        }

        const timer = setInterval(() => setNow(Date.now()), PLAYBACK_PROGRESS_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [
        active,
        player.is_playing,
        player.paused_for_cache,
        player.progress_anchor_ms,
        player.progress_ms,
        player.progress_sync_lost,
        player.started_at,
        player.timestamp,
    ]);

    return playbackProgressAt(player, now);
}

/**
 * Coordinates the use latest callback operation for the CLI UI runtime.
 *
 * @param callback Input value used by the use latest callback operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function useLatestCallback<T>(callback: T): React.MutableRefObject<T> {
    const ref = React.useRef(callback);

    React.useEffect(() => {
        ref.current = callback;
    }, [callback]);

    return ref;
}

/**
 * Coordinates the use sonex socket operation for the CLI UI runtime.
 *
 * @param url,onEvent,onConnectionChange,onClientError Input value used by the use sonex socket operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function useSonexSocket({
    url,
    onEvent,
    onConnectionChange,
    onClientError
}: {
    url: string;
    onEvent: (evt: ServerEvent) => void;
    onConnectionChange?: (connected: boolean) => void;
    onClientError?: (message: string, detail?: string) => void;
}) {
    const wsRef = React.useRef<WebSocket | null>(null);
    const onEventRef = useLatestCallback(onEvent);
    const onConnectionChangeRef = useLatestCallback(onConnectionChange);
    const onClientErrorRef = useLatestCallback(onClientError);

    React.useEffect(() => {
        let closedByUser = false;
        let connectionErrorShown = false;
        let reconnectTimer: NodeJS.Timeout | null = null;

        const connect = () => {
            const ws = new WebSocket(url);
            wsRef.current = ws;

            ws.onopen = () => {
                connectionErrorShown = false;
                onConnectionChangeRef.current?.(true);
            };
            ws.onclose = () => {
                onConnectionChangeRef.current?.(false);
                if (!closedByUser) {
                    reconnectTimer = setTimeout(connect, 1500);
                }
            };
            ws.onerror = (err: WebSocket.ErrorEvent) => {
                onConnectionChangeRef.current?.(false);
                if (!connectionErrorShown) {
                    const detail = err.message || undefined;
                    onClientErrorRef.current?.(`${API_NOT_RUNNING_MESSAGE}. ${API_NOT_RUNNING_DETAIL}`, detail);
                    connectionErrorShown = true;
                }
            };
            ws.onmessage = (msg: { data: { toString: () => string; }; }) => {
                try {
                    const data = JSON.parse(msg.data.toString());
                    onEventRef.current(data);
                } catch (err) {
                    const detail = err instanceof Error ? err.message : String(err);
                    onClientErrorRef.current?.("Invalid server message", detail);
                }
            };
        };

        connect();

        return () => {
            closedByUser = true;
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
            }
            wsRef.current?.close();
        };
    }, [url]);

    const send = React.useCallback((payload: ClientEvent): boolean => {
        const ws = wsRef.current;
        if (ws && ws.readyState === ws.OPEN) {
            ws.send(JSON.stringify(payload));
            return true;
        }
        return false;
    }, []);

    return { send };
}

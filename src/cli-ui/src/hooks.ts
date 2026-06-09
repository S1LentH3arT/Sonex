import React from 'react';
import WebSocket from 'ws';
import terminalImage from 'terminal-image';
import { API_NOT_RUNNING_DETAIL, API_NOT_RUNNING_MESSAGE } from './constants.js';
import type { ClientEvent, PlayerState, ServerEvent } from './types.js';

/**
 * Defines the playback progress interval ms constant.
 *
 * Stores stable configuration or display data consumed by hooks.ts.
 */
export const PLAYBACK_PROGRESS_INTERVAL_MS = 1000;

/**
 * Should use playback progress timer.
 *
 * Coordinates the should use playback progress timer operation for the CLI UI runtime.
 *
 * @param player Input value used by the should use playback progress timer operation.
 * @param active Input value used by the should use playback progress timer operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function shouldUsePlaybackProgressTimer(player: PlayerState, active = true): boolean {
    return active && player.is_playing === true;
}

/**
 * Playback progress at.
 *
 * Coordinates the playback progress at operation for the CLI UI runtime.
 *
 * @param player Input value used by the playback progress at operation.
 * @param now Input value used by the playback progress at operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function playbackProgressAt(player: PlayerState, now: number): number {
    /**
     * Defines the base constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const base = player.progress_ms ?? 0;
    /**
     * Defines the reference constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const reference = player.timestamp ?? player.started_at;
    /**
     * Defines the live offset constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const liveOffset = player.is_playing && reference ? Math.max(0, now - reference) : 0;
    /**
     * Defines the progress constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const progress = base + liveOffset;
    return player.duration_ms > 0 ? Math.min(player.duration_ms, progress) : progress;
}

/**
 * Use playback progress.
 *
 * Coordinates the use playback progress operation for the CLI UI runtime.
 *
 * @param player Input value used by the use playback progress operation.
 * @param active Input value used by the use playback progress operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function usePlaybackProgress(player: PlayerState, active = true): number {
    /**
     * Defines the [now, set now] constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const [now, setNow] = React.useState(Date.now());

    React.useEffect(() => {
        if (!shouldUsePlaybackProgressTimer(player, active)) {
            setNow(Date.now());
            return;
        }

        /**
         * Defines the timer constant.
         *
         * Stores stable configuration or display data consumed by hooks.ts.
         */
        const timer = setInterval(() => setNow(Date.now()), PLAYBACK_PROGRESS_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [active, player.is_playing, player.timestamp, player.started_at, player.progress_ms]);

    return playbackProgressAt(player, now);
}

/**
 * Use cover art.
 *
 * Coordinates the use cover art operation for the CLI UI runtime.
 *
 * @param url Input value used by the use cover art operation.
 * @param width Input value used by the use cover art operation.
 * @param height Input value used by the use cover art operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function useCoverArt(url: string | null, width = 32, height = 16): { art: string | null; failed: boolean } {
    /**
     * Defines the [art, set art] constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const [art, setArt] = React.useState<string | null>(null);
    /**
     * Defines the [failed, set failed] constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const [failed, setFailed] = React.useState(false);

    React.useEffect(() => {
        if (!url) {
            setArt(null);
            setFailed(false);
            return;
        }

        let cancelled = false;
        setArt(null);
        setFailed(false);

        /**
         * Defines the load function.
         *
         * Implements the load behavior used by hooks.ts.
         * @returns The computed result for the surrounding CLI UI flow.
         */
        const load = async () => {
            /**
             * Defines the start constant.
             *
             * Stores stable configuration or display data consumed by hooks.ts.
             */
            const start = Date.now();
            try {
                /**
                 * Defines the response constant.
                 *
                 * Stores stable configuration or display data consumed by hooks.ts.
                 */
                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                /**
                 * Defines the fetched at constant.
                 *
                 * Stores stable configuration or display data consumed by hooks.ts.
                 */
                const fetchedAt = Date.now();
                /**
                 * Defines the array buffer constant.
                 *
                 * Stores stable configuration or display data consumed by hooks.ts.
                 */
                const arrayBuffer = await response.arrayBuffer();
                /**
                 * Defines the rendered constant.
                 *
                 * Stores stable configuration or display data consumed by hooks.ts.
                 */
                const rendered = await terminalImage.buffer(Buffer.from(arrayBuffer), {
                    width,
                    height,
                    preserveAspectRatio: true,
                });
                if (process.env.SONEX_PLAYER_DEBUG === '1') {
                    /**
                     * Defines the decoded at constant.
                     *
                     * Stores stable configuration or display data consumed by hooks.ts.
                     */
                    const decodedAt = Date.now();
                    console.error(`[sonex-player-debug] cover fetch ${fetchedAt - start}ms decode ${decodedAt - fetchedAt}ms url=${url}`);
                }
                if (!cancelled) {
                    setArt(rendered);
                }
            } catch (err) {
                if (process.env.SONEX_PLAYER_DEBUG === '1') {
                    /**
                     * Defines the detail constant.
                     *
                     * Stores stable configuration or display data consumed by hooks.ts.
                     */
                    const detail = err instanceof Error ? err.message : String(err);
                    console.error(`[sonex-player-debug] cover fetch/decode failed after ${Date.now() - start}ms: ${detail}`);
                }
                if (!cancelled) {
                    setFailed(true);
                }
            }
        };

        void load();

        return () => {
            cancelled = true;
        };
    }, [url, width, height]);

    return { art, failed };
}

/**
 * Is http cover source.
 *
 * Coordinates the is http cover source operation for the CLI UI runtime.
 *
 * @param url Input value used by the is http cover source operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function isHttpCoverSource(url: string | null): boolean {
    return Boolean(url && /^https?:\/\//i.test(url));
}

/**
 * Use latest callback.
 *
 * Coordinates the use latest callback operation for the CLI UI runtime.
 *
 * @param callback Input value used by the use latest callback operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function useLatestCallback<T>(callback: T): React.MutableRefObject<T> {
    /**
     * Defines the ref constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const ref = React.useRef(callback);

    React.useEffect(() => {
        ref.current = callback;
    }, [callback]);

    return ref;
}

/**
 * Use sonex socket.
 *
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
    /**
     * Defines the ws ref constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const wsRef = React.useRef<WebSocket | null>(null);
    /**
     * Defines the on event ref constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const onEventRef = useLatestCallback(onEvent);
    /**
     * Defines the on connection change ref constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const onConnectionChangeRef = useLatestCallback(onConnectionChange);
    /**
     * Defines the on client error ref constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const onClientErrorRef = useLatestCallback(onClientError);

    React.useEffect(() => {
        let closedByUser = false;
        let connectionErrorShown = false;
        let reconnectTimer: NodeJS.Timeout | null = null;

        /**
         * Defines the connect function.
         *
         * Implements the connect behavior used by hooks.ts.
         * @returns The computed result for the surrounding CLI UI flow.
         */
        const connect = () => {
            /**
             * Defines the ws constant.
             *
             * Stores stable configuration or display data consumed by hooks.ts.
             */
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
                    /**
                     * Defines the detail constant.
                     *
                     * Stores stable configuration or display data consumed by hooks.ts.
                     */
                    const detail = err.message || undefined;
                    onClientErrorRef.current?.(`${API_NOT_RUNNING_MESSAGE}. ${API_NOT_RUNNING_DETAIL}`, detail);
                    connectionErrorShown = true;
                }
            };
            ws.onmessage = (msg: { data: { toString: () => string; }; }) => {
                try {
                    /**
                     * Defines the data constant.
                     *
                     * Stores stable configuration or display data consumed by hooks.ts.
                     */
                    const data = JSON.parse(msg.data.toString());
                    onEventRef.current(data);
                } catch (err) {
                    /**
                     * Defines the detail constant.
                     *
                     * Stores stable configuration or display data consumed by hooks.ts.
                     */
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

    /**
     * Defines the send constant.
     *
     * Stores stable configuration or display data consumed by hooks.ts.
     */
    const send = React.useCallback((payload: ClientEvent): boolean => {
        /**
         * Defines the ws constant.
         *
         * Stores stable configuration or display data consumed by hooks.ts.
         */
        const ws = wsRef.current;
        if (ws && ws.readyState === ws.OPEN) {
            ws.send(JSON.stringify(payload));
            return true;
        }
        return false;
    }, []);

    return { send };
}

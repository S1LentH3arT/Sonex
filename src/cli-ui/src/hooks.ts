import React from 'react';
import WebSocket from 'ws';
import terminalImage from 'terminal-image';
import {API_NOT_RUNNING_DETAIL, API_NOT_RUNNING_MESSAGE} from './constants.js';
import type {ClientEvent, PlayerState, ServerEvent} from './types.js';

export function usePlaybackProgress(player: PlayerState): number {
    const [now, setNow] = React.useState(Date.now());

    React.useEffect(() => {
        if (!player.is_playing) {
            setNow(Date.now());
            return;
        }

        const timer = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(timer);
    }, [player.is_playing, player.timestamp, player.started_at, player.progress_ms]);

    const base = player.progress_ms ?? 0;
    const reference = player.timestamp ?? player.started_at;
    const liveOffset = player.is_playing && reference ? Math.max(0, now - reference) : 0;
    return Math.min(player.duration_ms || 0, base + liveOffset);
}

export function useCoverArt(url: string | null, width = 32, height = 16): {art: string | null; failed: boolean} {
    const [art, setArt] = React.useState<string | null>(null);
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

        const load = async () => {
            try {
                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const arrayBuffer = await response.arrayBuffer();
                const rendered = await terminalImage.buffer(Buffer.from(arrayBuffer), {
                    width,
                    height,
                    preserveAspectRatio: true,
                });
                if (!cancelled) {
                    setArt(rendered);
                }
            } catch {
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

    return {art, failed};
}

export function useLatestCallback<T>(callback: T): React.MutableRefObject<T> {
    const ref = React.useRef(callback);

    React.useEffect(() => {
        ref.current = callback;
    }, [callback]);

    return ref;
}

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

    return {send};
}

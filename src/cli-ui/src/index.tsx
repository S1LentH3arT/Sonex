import React, {useState} from 'react';
import {render, Box, Text, useInput, useStdin} from 'ink';
import TextInput from 'ink-text-input';
import WebSocket from "ws";
import terminalImage from "terminal-image";

type ServerEvent =
    | { type: "chat"; role: ChatRole; text: string }
    | { type: "activity"; id: string; kind: ActivityKind; title: string; detail?: string | null; status?: ActivityStatus | null; timestamp: number }
    | { type: "status"; phase: string; message: string; tokens?: number | null; elapsed_ms?: number | null; step?: number; max_steps?: number }
    | { type: "queue"; tracks: Array<{ index: string; title: string; artist: string; duration: string }> }
    | { type: "search_results"; tracks: TrackSummary[] }
    | { type: "player"; state: PlayerState }
    | { type: "cover"; url: string }
    | { type: "error"; message: string; detail?: string | null; recoverable?: boolean | null }
    | { type: "confirm"; id: string; tool_name: string; tool_args: Record<string, unknown>; message?: string | null; choices?: ConfirmChoice[] | null }
    | { type: "spotify_setup"; step: string; title: string; message: string; prompt?: string | null; mask?: boolean | null; active?: boolean | null }
    | { type: "auth_setup"; provider: string; step: string; title: string; message: string; prompt?: string | null; mask?: boolean | null; active?: boolean | null; methods?: AuthMethodChoice[] | null };

type ClientEvent =
    | { type: "user_input"; text: string }
    | { type: "confirm_result"; id: string; decision: string }
    | { type: "setup_input"; value: string }
    | { type: "auth_setup_input"; value: string };

type ConfirmChoice = {
    value: string;
    label: string;
};

type ConfirmState = {
    id: string;
    tool_name: string;
    tool_args: Record<string, unknown>;
    message: string;
    choices: ConfirmChoice[];
} | null;

type SpotifySetupState = {
    step: string;
    title: string;
    message: string;
    prompt?: string | null;
    mask?: boolean | null;
    active: boolean;
} | null;

type AuthMethodChoice = {
    value: string;
    label: string;
};

type AuthSetupState = {
    provider: string;
    step: string;
    title: string;
    message: string;
    prompt?: string | null;
    mask?: boolean | null;
    active: boolean;
    methods?: AuthMethodChoice[] | null;
} | null;

type ChatRole = "user" | "agent";

type ActivityKind = "tool" | "status" | "error" | "confirm";

type ActivityStatus = "pending" | "success" | "error";

type ActivityItem = {
    id: string;
    kind: ActivityKind;
    title: string;
    detail?: string | null;
    status?: ActivityStatus | null;
    timestamp: number;
};

type PlayerState = {
    name: string;
    artist: string;
    album: string;
    duration_ms: number;
    progress_ms?: number;
    timestamp?: number;
    started_at?: number;
    is_playing?: boolean;
};

type TrackSummary = {
    index: string;
    name: string;
    title: string;
    artist: string;
    album: string;
    duration: string;
    duration_ms: number;
    uri?: string | null;
    spotify_url?: string | null;
    album_cover_url?: string | null;
    recommendation_reason?: string | null;
};

type ChatBubbleProps = {
    role: ChatRole;
    content: string;
};

type ChatItem = {
    role: ChatRole;
    content: string;
};

type LayoutMode = "compact" | "full";

type PlayerPaneVariant = "compact" | "full";

type PromptInputProps = {
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    focus: boolean;
    placeholder: string;
    mask?: string;
};

type SlashCommandSuggestion = {
    name: string;
    usage: string;
    description: string;
    needsArgument: boolean;
};

const wsUrl = process.env.SONEX_WS_URL ?? "ws://localhost:9001/ws";

const APP_VERSION = "1.0.1";
const DEFAULT_MODEL_NAME = "GPT-5.5";
const BORDER_BLUE = "#3b82f6";
const BORDER_BLUE_SOFT = "#9fd9ff";
const APP_MODE_LABEL = "api billing";
const APP_TIP_PLACEHOLDER = "Tips: coming soon";
const MAX_CHAT_ITEMS = 80;
const MAX_ACTIVITY_ITEMS = 80;
const DEFAULT_CONFIRM_CHOICES: ConfirmChoice[] = [
    {value: "allow_once", label: "Yes"},
    {value: "deny", label: "No"},
];
const SLASH_COMMANDS: SlashCommandSuggestion[] = [
    {name: "help", usage: "/help", description: "Show available commands", needsArgument: false},
    {name: "recommend", usage: "/recommend [taste]", description: "Recommend songs", needsArgument: true},
    {name: "random", usage: "/random", description: "Play from recent songs", needsArgument: false},
    {name: "search", usage: "/search <query>", description: "Search songs", needsArgument: true},
    {name: "play", usage: "/play <query|number>", description: "Play a song", needsArgument: true},
    {name: "setup", usage: "/setup [provider]", description: "Configure music", needsArgument: true},
];
const API_NOT_RUNNING_MESSAGE = "Sonex API is not running";
const API_NOT_RUNNING_DETAIL = "Start with `sonex`, or run `sonex api` before `sonex tui`.";

type MascotSegment = {
    text: string;
    fg?: string; // 上半部分颜色
    bg?: string; // 下半部分颜色
};

const SONEX_MASCOT: MascotSegment[][] = [
    [
        {text: "    "},
        {text: "▄", fg: "#000000"},
        {text: "▀▀▀▀▀", fg: "#000000", bg: "#f4f1f3"},
        {text: "▄", fg: "#000000"},
    ],
    [
        {text: "  "},
        {text: "▄", fg: "#000000"},
        {text: "▀", fg: "#000000", bg: "#f4f1f3"},
        {text: "▀", fg: "#f4f1f3", bg: "#000000"},
        {text: "▀▀▀▀▀", fg: "#000000", bg: "#9fd9ff"},
        {text: "▀", fg: "#f4f1f3", bg: "#000000"},
        {text: "▄", fg: "#000000"},
    ],
    [
        {text: "  "},
        {text: "█", fg: "#000000"},
        {text: "▀", fg: "#f4f1f3", bg: "#000000"},
        {text: "▀", fg: "#000000", bg: "#9fd9ff"},
        {text: "██████", fg: "#9fd9ff"},
        {text: "▀", fg: "#4b5161", bg: "#9fd9ff"},
        {text: "▄", fg: "#4b5161"},
    ],
    [
        {text: " "},
        {text: "█", fg: "#000000"},
        {text: "██", fg: "#f4f1f3"},
        {text: "█", fg: "#000000"},
        {text: "██", fg: "#9fd9ff"},
        {text: "█", fg: "#000000"},
        {text: "██", fg: "#9fd9ff"},
        {text: "█", fg: "#000000"},
        {text: "█", fg: "#9fd9ff"},
        {text: "█", fg: "#4b5161"},
    ],
    [
        {text: " "},
        {text: "▀", fg: "#000000"},
        {text: "▀▀", fg: "#f4f1f3", bg: "#000000"},
        {text: "▀", fg: "#000000", bg: "#9fd9ff"},
        {text: "███████", fg: "#9fd9ff"},
        {text: "▀", fg: "#4b5161"},
    ],
    [
        {text: "  "},
        {text: "▄", fg: "#4b5161"},
        {text: "▀", fg: "#4b5161", bg: "#9fd9ff"},
        {text: "██████", fg: "#9fd9ff"},
        {text: "█", fg: "#9fd9ff"},
        {text: "▀", fg: "#9fd9ff"},
    ],
    [
        {text: "  "},
        {text: "▀", fg: "#4b5161"},
        {text: "▀", fg: "#9fd9ff"},
        {text: "▀", fg: "#9fd9ff"},
        {text: "█████", fg: "#9fd9ff"},
        {text: "▀", fg: "#9fd9ff"},
    ],
    // [
    //     {text: "      "},
    //     {text: "████████", color: "#4b5161"},
    // ],
    // [
    //     {text: "     "},
    //     {text: "██", color: "#4b5161"},
    //     {text: "██████", color: "#f4f1f3"},
    //     {text: "██", color: "#4b5161"},
    // ],
    // [
    //     {text: "    "},
    //     {text: "██", color: "#4b5161"},
    //     {text: "█", color: "#f4f1f3"},
    //     {text: "██████", color: "#4b5161"},
    //     {text: "█", color: "#f4f1f3"},
    //     {text: "██", color: "#4b5161"},
    // ],
    // [
    //     {text: "   "},
    //     {text: "██", color: "#4b5161"},
    //     {text: "█", color: "#f4f1f3"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "██████", color: "#9fd9ff"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "█", color: "#f4f1f3"},
    //     {text: "█", color: "#4b5161"},
    // ],
    // [
    //     {text: "  "},
    //     {text: "██", color: "#4b5161"},
    //     {text: "█", color: "#f4f1f3"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "████████", color: "#9fd9ff"},
    //     {text: "██", color: "#4b5161"},
    // ],
    // [
    //     {text: " "},
    //     {text: "████", color: "#4b5161"},
    //     {text: "██████████", color: "#9fd9ff"},
    //     {text: "██", color: "#4b5161"},
    // ],
    // [
    //     {text: "██", color: "#4b5161"},
    //     {text: "██", color: "#f4f1f3"},
    //     {text: "██", color: "#4b5161"},
    //     {text: "██████████", color: "#9fd9ff"},
    //     {text: "█", color: "#4b5161"},
    //     {text: " "},
    // ],
    // [
    //     {text: "█", color: "#4b5161"},
    //     {text: "████", color: "#f4f1f3"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "██████████", color: "#9fd9ff"},
    //     {text: "██", color: "#4b5161"},
    // ],
    // [
    //     {text: "█", color: "#4b5161"},
    //     {text: "████", color: "#f4f1f3"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "███", color: "#9fd9ff"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "████", color: "#9fd9ff"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "██", color: "#9fd9ff"},
    //     {text: "█", color: "#4b5161"},
    // ],
    // [
    //     {text: "█", color: "#4b5161"},
    //     {text: "████", color: "#f4f1f3"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "███", color: "#9fd9ff"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "████", color: "#9fd9ff"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "██", color: "#9fd9ff"},
    //     {text: "█", color: "#4b5161"},
    // ],
    // [
    //     {text: "██", color: "#4b5161"},
    //     {text: "██", color: "#f4f1f3"},
    //     {text: "██", color: "#4b5161"},
    //     {text: "███████████", color: "#9fd9ff"},
    //     {text: "█", color: "#4b5161"},
    // ],
    // [
    //     {text: " "},
    //     {text: "████", color: "#4b5161"},
    //     {text: "███████████", color: "#9fd9ff"},
    //     {text: "██", color: "#4b5161"},
    // ],
    // [
    //     {text: "  "},
    //     {text: "█", color: "#4b5161"},
    //     {text: "████████████", color: "#9fd9ff"},
    //     {text: "██", color: "#4b5161"},
    // ],
    // [
    //     {text: " "},
    //     {text: "██", color: "#4b5161"},
    //     {text: "████████████", color: "#9fd9ff"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "  "},
    // ],
    // [
    //     {text: " "},
    //     {text: "█", color: "#4b5161"},
    //     {text: "████████████", color: "#9fd9ff"},
    //     {text: "██", color: "#4b5161"},
    //     {text: "  "},
    // ],
    // [
    //     {text: " "},
    //     {text: "█", color: "#4b5161"},
    //     {text: "████████████", color: "#9fd9ff"},
    //     {text: "█", color: "#4b5161"},
    //     {text: "   "},
    // ],
    // [
    //     {text: " "},
    //     {text: "█████", color: "#4b5161"},
    //     {text: "███████", color: "#9fd9ff"},
    //     {text: "██", color: "#4b5161"},
    //     {text: "   "},
    // ],
    // [
    //     {text: "     "},
    //     {text: "██████████", color: "#4b5161"},
    //     {text: "    "},
    // ],
];

function formatElapsed(ms?: number | null): string {
    if (!ms) return "00m 00s";
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
    const seconds = (totalSeconds % 60).toString().padStart(2, "0");
    return `${minutes}m ${seconds}s`;
}

function formatDuration(ms: number): string {
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = (totalSeconds % 60).toString().padStart(2, "0");
    return `${minutes}:${seconds}`;
}

function buildProgressBar(progressMs: number, durationMs: number, width = 18): string {
    if (durationMs <= 0) return "─".repeat(width);
    const ratio = Math.min(1, Math.max(0, progressMs / durationMs));
    const filled = Math.round(ratio * width);
    return "━".repeat(filled) + "─".repeat(width - filled);
}

function slashCommandSuggestions(input: string): SlashCommandSuggestion[] {
    const trimmed = input.trimStart();
    if (!trimmed.startsWith("/")) return [];
    const token = trimmed.slice(1).split(/\s+/, 1)[0]?.toLowerCase() ?? "";
    return SLASH_COMMANDS.filter((command) => command.name.startsWith(token)).slice(0, 6);
}

function slashCommandToken(input: string): string {
    const trimmed = input.trimStart();
    if (!trimmed.startsWith("/")) return "";
    return trimmed.slice(1).split(/\s+/, 1)[0]?.toLowerCase() ?? "";
}

function matchingSlashCommand(input: string): SlashCommandSuggestion | undefined {
    const token = slashCommandToken(input);
    return SLASH_COMMANDS.find((command) => command.name === token);
}

function hasSlashCommandArguments(input: string): boolean {
    const trimmed = input.trimStart();
    const spaceIndex = trimmed.indexOf(" ");
    return spaceIndex !== -1 && trimmed.slice(spaceIndex + 1).trim().length > 0;
}

function completeSlashCommand(command: SlashCommandSuggestion): string {
    return command.needsArgument ? `/${command.name} ` : `/${command.name}`;
}

function usePlaybackProgress(player: PlayerState): number {
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

function trimList<T>(items: T[], limit: number): T[] {
    return items.slice(Math.max(0, items.length - limit));
}

function upsertActivity(items: ActivityItem[], item: ActivityItem): ActivityItem[] {
    const index = items.findIndex((existing) => existing.id === item.id);
    if (index === -1) {
        return trimList([...items, item], MAX_ACTIVITY_ITEMS);
    }

    const next = [...items];
    next[index] = {...next[index], ...item};
    return trimList(next, MAX_ACTIVITY_ITEMS);
}

function buildErrorActivity(message: string, detail?: string | null): ActivityItem {
    return {
        id: `error_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        kind: "error",
        title: message,
        detail,
        status: "error",
        timestamp: Date.now(),
    };
}

function useCoverArt(url: string | null, width = 32, height = 16): {art: string | null; failed: boolean} {
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

function useLatestCallback<T>(callback: T): React.MutableRefObject<T> {
    const ref = React.useRef(callback);

    React.useEffect(() => {
        ref.current = callback;
    }, [callback]);

    return ref;
}

function useSonexSocket({
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

    const send = React.useCallback((payload: ClientEvent) => {
        const ws = wsRef.current;
        if (ws && ws.readyState === ws.OPEN) {
            ws.send(JSON.stringify(payload));
        }
    }, []);

    return {send};
}

const Mascot = () => {
  return (
    <Box width={16} flexDirection="column" marginRight={3}>
      {SONEX_MASCOT.map((row, rowIndex) => (
        <Text key={rowIndex}>
          {row.map((segment, segmentIndex) => (
            <Text key={segmentIndex} color={segment.fg} backgroundColor={segment.bg}>
              {segment.text}
            </Text>
          ))}
        </Text>
      ))}
    </Box>
  );
};

const BrandBlock = () => (
    <Box minHeight={6} paddingX={1} paddingY={1} borderBottom={true} borderStyle="single" borderColor={BORDER_BLUE}>
        <Mascot/>
        <Box flexDirection="column" justifyContent="flex-start">
            <Text><Text bold color="#fff4f6">Sonex CLI</Text> <Text color="#bf98a7">v{APP_VERSION}</Text></Text>
            <Text><Text color="#d8bcc7">{DEFAULT_MODEL_NAME}</Text> <Text color="#9d7787">•</Text> <Text color="#d8bcc7">{APP_MODE_LABEL}</Text></Text>
            <Text color="#bf98a7">~/dev/sonex</Text>
            <Text color={BORDER_BLUE_SOFT}>{APP_TIP_PLACEHOLDER}</Text>
        </Box>
    </Box>
);

const PromptInput = ({input, setInput, onSubmit, focus, placeholder, mask}: PromptInputProps) => (
    <TextInput
        value={input}
        onChange={setInput}
        onSubmit={onSubmit}
        focus={focus}
        placeholder={placeholder}
        mask={mask}
    />
);

const SlashCommandList = ({suggestions, selectedIndex}: {
    suggestions: SlashCommandSuggestion[];
    selectedIndex: number;
}) => {
    if (suggestions.length === 0) return null;

    return (
        <Box flexDirection="column" paddingX={1} paddingBottom={1}>
            {suggestions.map((command, index) => (
                <Text key={command.name}>
                    <Text color={index === selectedIndex ? "#fff4f6" : "#7f5d6b"}>
                        {index === selectedIndex ? "> " : "  "}
                    </Text>
                    <Text color={index === selectedIndex ? "#fff4f6" : "#bf98a7"}>{command.usage}</Text>
                    <Text color="#7f5d6b"> - </Text>
                    <Text color="#9d7787">{command.description}</Text>
                </Text>
            ))}
        </Box>
    );
};

const ChatBubble = ({role, content}: ChatBubbleProps) => {
    const isUser = role === "user";
    const color = isUser ? "#fff6f8" : "#f6e9ee";
    const borderLeftColor = isUser ? BORDER_BLUE : BORDER_BLUE_SOFT;

    return (
        <Box paddingX={2} marginBottom={1} borderStyle="single" borderTop={false} borderRight={false}
             borderBottom={false} borderLeft={true} borderColor={borderLeftColor} flexDirection="column" width="100%">
            <Text color={color}>{content}</Text>
        </Box>
    );
};

const ChatPane = ({items}: { items: ChatItem[] }) => (
    <Box flexDirection="column" flexGrow={1} paddingX={1} height="100%">
        <Box marginBottom={1}>
            <Text bold color="#f3b2c6">Conversation</Text>
        </Box>
        <Box flexDirection="column" flexGrow={1}>
            {items.length === 0 ? (
                <Text color="#7f5d6b">No messages yet.</Text>
            ) : (
                items.map((chat, idx) => (
                    <ChatBubble key={idx} role={chat.role} content={chat.content}/>
                ))
            )}
        </Box>
    </Box>
);

const QueuePane = ({tracks}: { tracks: Array<{ index: string; title: string; artist: string; duration: string }> }) => (
    <Box flexDirection="column" minHeight={9} padding={1} paddingX={2} borderBottom={true} borderStyle="single"
         borderColor={BORDER_BLUE}>
        <Box marginBottom={1}>
            <Text bold color="#f3b2c6">Queue / Playlist</Text>
        </Box>
        <Box flexDirection="column" paddingTop={1}>
            {tracks.length === 0 ? (
                <Text color="#7f5d6b">Queue is empty.</Text>
            ) : tracks.map((track, idx) => {
                const marker = track.index === "01" ? <Text color="#f3b2c6">{">>"}</Text> :
                    <Text color="#7f5d6b">{".."}</Text>;
                return (
                    <Box key={idx} flexDirection="column" marginBottom={1}>
                        <Text>{marker} <Text color="#bf98a7">{track.index}</Text> <Text
                            color="#fff4f6">{track.title}</Text></Text>
                        <Text> <Text color="#bf98a7">{track.artist}</Text> <Text color="#7f5d6b">•</Text> <Text
                            color="#bf98a7">{track.duration}</Text></Text>
                    </Box>
                );
            })}
        </Box>
    </Box>
);

const SearchResultsPane = ({tracks}: { tracks: TrackSummary[] }) => (
    <Box flexDirection="column" minHeight={12} padding={1} paddingX={2} borderBottom={true} borderStyle="single"
         borderColor={BORDER_BLUE}>
        <Box marginBottom={1}>
            <Text bold color="#f3b2c6">Search Results</Text>
        </Box>
        <Box flexDirection="column">
            {tracks.length === 0 ? (
                <Text color="#7f5d6b">No Spotify results yet.</Text>
            ) : tracks.slice(0, 6).map((track, idx) => {
                const marker = idx === 0 ? <Text color="#f3b2c6">{">>"}</Text> :
                    <Text color="#7f5d6b">{".."}</Text>;
                return (
                    <Box key={`${track.uri ?? track.index}_${idx}`} flexDirection="column" marginBottom={1}>
                        <Text>{marker} <Text color="#bf98a7">{track.index}</Text> <Text
                            color="#fff4f6">{track.title || track.name}</Text></Text>
                        <Text> <Text color="#bf98a7">{track.artist}</Text> <Text color="#7f5d6b">•</Text> <Text
                            color="#bf98a7">{track.album}</Text> <Text color="#7f5d6b">•</Text> <Text
                            color="#bf98a7">{track.duration}</Text></Text>
                        {track.recommendation_reason ? (
                            <Text color="#9d7787"> {track.recommendation_reason}</Text>
                        ) : null}
                    </Box>
                );
            })}
        </Box>
    </Box>
);

const ActivityPane = ({items, confirm, confirmIndex, spotifySetup, authSetup}: {
    items: ActivityItem[];
    confirm: ConfirmState;
    confirmIndex: number;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
}) => {
    const colors: Record<ActivityKind, string> = {
        tool: "#8fd3ff",
        status: "#bf98a7",
        error: "#ff9c9c",
        confirm: "#f3b2c6",
    };

    return (
        <Box flexDirection="column" flexGrow={1} minHeight={14} padding={1} paddingX={2} borderBottom={true}
             borderStyle="single" borderColor={BORDER_BLUE}>
            <Box marginBottom={1}>
                <Text bold color="#f3b2c6">Activity</Text>
            </Box>
            {confirm && (
                <Box flexDirection="column" marginBottom={1} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE_SOFT}>
                    <Text color="#fff4f6">{confirm.message}</Text>
                    <Text color="#bf98a7">{confirm.tool_name} {JSON.stringify(confirm.tool_args)}</Text>
                    <Box flexDirection="column">
                        {confirm.choices.map((choice, idx) => (
                            <Text key={choice.value} color={confirmIndex === idx ? "#fff4f6" : "#7f5d6b"}>
                                {confirmIndex === idx ? "> " : "  "}{choice.label}
                            </Text>
                        ))}
                    </Box>
                </Box>
            )}
            {spotifySetup && (
                <Box flexDirection="column" marginBottom={1} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE_SOFT}>
                    <Text color="#fff4f6">{spotifySetup.title}</Text>
                    <Text color="#bf98a7">{spotifySetup.message}</Text>
                    {spotifySetup.active && spotifySetup.prompt ? (
                        <Text color="#9d7787">Input: {spotifySetup.prompt}</Text>
                    ) : null}
                </Box>
            )}
            {authSetup && (
                <Box flexDirection="column" marginBottom={1} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE_SOFT}>
                    <Text color="#fff4f6">{authSetup.title}</Text>
                    <Text color="#bf98a7">{authSetup.message}</Text>
                    {authSetup.methods && authSetup.methods.length > 0 ? (
                        <Text color="#9d7787">
                            {authSetup.methods.map((method) => method.value).join(" / ")}
                        </Text>
                    ) : null}
                    {authSetup.active && authSetup.prompt ? (
                        <Text color="#9d7787">Input: {authSetup.prompt}</Text>
                    ) : null}
                </Box>
            )}
            <Box flexDirection="column" flexGrow={1}>
                {items.length === 0 ? (
                    <Text color="#7f5d6b">Waiting for agent activity.</Text>
                ) : (
                    items.map((item) => {
                        const statusColor = item.status === "error" ? "#ff9c9c" :
                            item.status === "success" ? "#a4e7b1" : "#bf98a7";
	                        return (
	                            <Box key={item.id} flexDirection="column" marginBottom={1} borderStyle="single"
	                                 borderTop={false} borderRight={false} borderBottom={false} borderLeft={true}
	                                 borderColor={BORDER_BLUE_SOFT} paddingX={1}>
                                <Text>
                                    <Text color={colors[item.kind]}>{item.kind}</Text>
                                    <Text color="#7f5d6b"> • </Text>
                                    <Text color={statusColor}>{item.status ?? "pending"}</Text>
                                </Text>
                                <Text color="#fff4f6">{item.title}</Text>
                                {item.detail ? <Text color="#bf98a7">{item.detail}</Text> : null}
                            </Box>
                        );
                    })
                )}
            </Box>
        </Box>
    );
};

const PlayerPane = ({player, coverUrl, variant = "full"}: {
    player: PlayerState,
    coverUrl: string | null,
    variant?: PlayerPaneVariant
}) => {
    const compact = variant === "compact";
    const {art, failed} = useCoverArt(coverUrl, compact ? 14 : 32, compact ? 7 : 16);
    const duration = formatDuration(player.duration_ms);
    const progressMs = usePlaybackProgress(player);
    const progress = formatDuration(progressMs);
    const progressBar = buildProgressBar(progressMs, player.duration_ms, compact ? 14 : 18);

    return (
        <Box flexDirection="column" minHeight={compact ? 8 : 20} padding={1} paddingX={compact ? 1 : 2}>
            <Box marginBottom={compact ? 0 : 1}>
                <Text bold color="#f3b2c6">{compact ? "Playing" : "Now Playing"}</Text>
            </Box>
            <Box marginTop={compact ? 0 : 1}>
                {!compact && (
                    <Box width={36} paddingRight={2} flexDirection="column">
                        {art ? (
                            <Text>{art}</Text>
                        ) : coverUrl ? (
                            <Text color={failed ? "#ff9c9c" : "#7f5d6b"}>
                                {failed ? `Cover unavailable: ${coverUrl}` : "Loading cover..."}
                            </Text>
                        ) : (
                            <Text color="#7f5d6b">No cover art.</Text>
                        )}
                    </Box>
                )}
                {compact && art ? (
                    <Box width={18} paddingRight={1} flexDirection="column">
                        <Text>{art}</Text>
                    </Box>
                ) : null}
                <Box flexDirection="column" flexGrow={1} paddingTop={compact ? 0 : 1}>
                    <Text bold color="#fff4f6">{player.name}</Text>
                    <Text color="#bf98a7">{player.artist}</Text>
                    {!compact || player.album !== "-" ? <Text color="#bf98a7">{player.album}</Text> : null}
                    <Box marginTop={1}>
                        <Text>
                            <Text color="#bf98a7">{progress}</Text> <Text color="#7f5d6b">{progressBar}</Text> <Text
                            color="#bf98a7">{duration}</Text>
                        </Text>
                    </Box>
                </Box>
            </Box>
        </Box>
    );
};

const CompactConversation = ({items, statusText}: {items: ChatItem[]; statusText: string}) => {
    const visibleItems = items.slice(-2);

    return (
        <Box flexDirection="column" paddingX={1} paddingY={1} minHeight={4}>
            {visibleItems.length === 0 ? (
                <Text color="#7f5d6b">{statusText}</Text>
            ) : (
                visibleItems.map((item, idx) => (
                    <Text key={idx} color={item.role === "user" ? "#fff4f6" : "#bf98a7"}>
                        <Text color="#7f5d6b">{item.role === "user" ? ">" : "<"}</Text> {item.content}
                    </Text>
                ))
            )}
        </Box>
    );
};

const CompactConfirm = ({confirm, confirmIndex}: {confirm: ConfirmState; confirmIndex: number}) => {
    if (!confirm) return null;

    return (
        <Box flexDirection="column" paddingX={1} paddingY={1} borderTop={true} borderStyle="single" borderColor={BORDER_BLUE}>
            <Text color="#fff4f6">{confirm.message}</Text>
            {confirm.choices.map((choice, idx) => (
                <Text key={choice.value} color={confirmIndex === idx ? "#fff4f6" : "#7f5d6b"}>
                    {confirmIndex === idx ? "> " : "  "}{choice.label}
                </Text>
            ))}
        </Box>
    );
};

const CompactSetup = ({spotifySetup, authSetup}: {spotifySetup: SpotifySetupState; authSetup: AuthSetupState}) => {
    const setup = authSetup ?? spotifySetup;
    if (!setup) return null;

    return (
        <Box flexDirection="column" paddingX={1} paddingY={1} borderTop={true} borderStyle="single" borderColor={BORDER_BLUE}>
            <Text color="#fff4f6">{setup.title}</Text>
            <Text color="#bf98a7">{setup.message}</Text>
        </Box>
    );
};

const CompactShell = ({
    input,
    setInput,
    onSubmit,
    inputPlaceholder,
    inputMask,
    inputFocus,
    chatItems,
    statusText,
    confirm,
    confirmIndex,
    spotifySetup,
    authSetup,
    player,
    coverUrl,
    showPlayer,
    slashSuggestions,
    slashIndex,
}: {
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    inputPlaceholder: string;
    inputMask?: string;
    inputFocus: boolean;
    chatItems: ChatItem[];
    statusText: string;
    confirm: ConfirmState;
    confirmIndex: number;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
    player: PlayerState;
    coverUrl: string | null;
    showPlayer: boolean;
    slashSuggestions: SlashCommandSuggestion[];
    slashIndex: number;
}) => (
    <Box width={74} flexDirection="column" paddingX={1} paddingTop={1}>
        <Box flexDirection="column" borderStyle="single" borderColor={BORDER_BLUE}>
            <Box minHeight={6} paddingX={1} paddingY={1} borderBottom={true} borderStyle="single" borderColor={BORDER_BLUE}>
                <Mascot/>
                <Box flexDirection="column" paddingLeft={1}>
                    <Text><Text bold color="#fff4f6">Sonex</Text> <Text color="#bf98a7">v{APP_VERSION}</Text></Text>
                    <Text><Text color="#d8bcc7">{DEFAULT_MODEL_NAME}</Text> <Text color="#9d7787">•</Text> <Text color="#bf98a7">{APP_MODE_LABEL}</Text></Text>
                    <Text color={BORDER_BLUE_SOFT}>{APP_TIP_PLACEHOLDER}</Text>
                </Box>
            </Box>
            {showPlayer ? (
                <PlayerPane player={player} coverUrl={coverUrl} variant="compact"/>
            ) : (
                <CompactConversation items={chatItems} statusText={statusText}/>
            )}
            <CompactConfirm confirm={confirm} confirmIndex={confirmIndex}/>
            <CompactSetup spotifySetup={spotifySetup} authSetup={authSetup}/>
            <Box borderTop={true} borderStyle="single" borderColor={BORDER_BLUE} paddingX={1} paddingY={1}>
                <Box flexDirection="column">
                    <SlashCommandList suggestions={slashSuggestions} selectedIndex={slashIndex}/>
                    <Box>
                        <Text color="#7f5d6b">{"> "}</Text>
                        <PromptInput
                            input={input}
                            setInput={setInput}
                            onSubmit={onSubmit}
                            focus={inputFocus}
                            placeholder={inputPlaceholder}
                            mask={inputMask}
                        />
                    </Box>
                </Box>
            </Box>
        </Box>
    </Box>
);

const FullShell = ({
    input,
    setInput,
    onSubmit,
    inputPlaceholder,
    inputMask,
    inputFocus,
    chatItems,
    activityItems,
    queueItems,
    searchItems,
    player,
    statusText,
    elapsed,
    tokens,
    coverUrl,
    confirm,
    confirmIndex,
    spotifySetup,
    authSetup,
    slashSuggestions,
    slashIndex,
}: {
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    inputPlaceholder: string;
    inputMask?: string;
    inputFocus: boolean;
    chatItems: ChatItem[];
    activityItems: ActivityItem[];
    queueItems: Array<{ index: string; title: string; artist: string; duration: string }>;
    searchItems: TrackSummary[];
    player: PlayerState;
    statusText: string;
    elapsed: string;
    tokens: string;
    coverUrl: string | null;
    confirm: ConfirmState;
    confirmIndex: number;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
    slashSuggestions: SlashCommandSuggestion[];
    slashIndex: number;
}) => (
    <Box width="100%" height="100%" flexDirection="column" paddingX={1} paddingTop={1}>
        <Box width="100%" flexGrow={1} borderStyle="single" borderColor={BORDER_BLUE}>
            <Box width="45%" minWidth={48} flexDirection="column" borderRight={true} borderStyle="single"
                 borderColor={BORDER_BLUE}>
                <BrandBlock/>
                <ChatPane items={chatItems}/>
                <Box paddingX={1} height={1}>
                    <Text color="#bf98a7">
                        {statusText} <Text color="#7f5d6b">•</Text> <Text color="#d8bcc7">{elapsed}</Text> <Text
                        color="#7f5d6b">•</Text><Text color="#d8bcc7">{tokens}</Text>
                    </Text>
                </Box>
                <Box borderTop={true} borderStyle="single" borderColor={BORDER_BLUE} padding={1} flexDirection="column">
                    <SlashCommandList suggestions={slashSuggestions} selectedIndex={slashIndex}/>
                    <Box paddingX={1}>
                        <PromptInput
                            input={input}
                            setInput={setInput}
                            onSubmit={onSubmit}
                            focus={inputFocus}
                            placeholder={inputPlaceholder}
                            mask={inputMask}
                        />
                    </Box>
                </Box>
            </Box>

            <Box width="55%" minWidth={62} flexDirection="column">
                <ActivityPane items={activityItems} confirm={confirm} confirmIndex={confirmIndex} spotifySetup={spotifySetup} authSetup={authSetup}/>
                <SearchResultsPane tracks={searchItems}/>
                <QueuePane tracks={queueItems}/>
                <PlayerPane player={player} coverUrl={coverUrl}/>
            </Box>
        </Box>
    </Box>
);

const App = () => {
    const {isRawModeSupported} = useStdin();
    const rawModeAvailable = Boolean(isRawModeSupported && typeof process.stdin.setRawMode === "function");
    const [input, setInput] = useState("");
    const [chatItems, setChatItems] = useState<ChatItem[]>([]);
    const [activityItems, setActivityItems] = useState<ActivityItem[]>([]);
    const [queueItems, setQueueItems] = useState<Array<{
        index: string;
        title: string;
        artist: string;
        duration: string
    }>>([]);
    const [searchItems, setSearchItems] = useState<TrackSummary[]>([]);
    const [player, setPlayer] = useState<PlayerState>({name: "-", artist: "-", album: "-", duration_ms: 0, progress_ms: 0, is_playing: false});
    const [statusText, setStatusText] = useState("Snoozing...");
    const [elapsed, setElapsed] = useState("00m 00s");
    const [tokens, setTokens] = useState("0 tokens");
    const [coverUrl, setCoverUrl] = useState<string | null>(null);
    const [confirm, setConfirm] = useState<ConfirmState>(null);
    const [confirmIndex, setConfirmIndex] = useState(0); // 0=Yes, 1=No
    const [spotifySetup, setSpotifySetup] = useState<SpotifySetupState>(null);
    const [authSetup, setAuthSetup] = useState<AuthSetupState>(null);
    const [layoutMode, setLayoutMode] = useState<LayoutMode>("compact");
    const [hasPlaybackIntent, setHasPlaybackIntent] = useState(false);
    const [manualLayoutOverride, setManualLayoutOverride] = useState(false);
    const [slashIndex, setSlashIndex] = useState(0);
    const [slashMenuDismissedFor, setSlashMenuDismissedFor] = useState<string | null>(null);
    const slashSuggestions = authSetup?.active || spotifySetup?.active ? [] : slashCommandSuggestions(input);
    const slashInput = input.trimStart();
    const isSlashInput = slashInput.startsWith("/");
    const isSlashMenuActive = rawModeAvailable && !confirm && isSlashInput && slashMenuDismissedFor !== input && slashSuggestions.length > 0;
    const selectedSlashCommand = slashSuggestions[Math.min(slashIndex, Math.max(0, slashSuggestions.length - 1))];

    React.useEffect(() => {
        setSlashIndex((prev) => Math.min(prev, Math.max(0, slashSuggestions.length - 1)));
    }, [slashSuggestions.length]);

    React.useEffect(() => {
        if (!isSlashInput || authSetup?.active || spotifySetup?.active || slashSuggestions.length === 0) {
            setSlashMenuDismissedFor(null);
            setSlashIndex(0);
        }
    }, [authSetup?.active, isSlashInput, slashSuggestions.length, spotifySetup?.active]);

    const updateInput = React.useCallback((value: string) => {
        const sanitized = value.replace(/\x1B/g, "");
        setInput(sanitized);
        if (sanitized !== slashMenuDismissedFor) {
            setSlashMenuDismissedFor(null);
        }
    }, [slashMenuDismissedFor]);

	    const showError = React.useCallback((message: string, detail?: string | null, includeActivity = true) => {
	        if (includeActivity) {
	            setActivityItems((prev) => upsertActivity(prev, buildErrorActivity(message, detail)));
	        }
	        setChatItems((prev) => trimList([...prev, {role: "agent", content: message}], MAX_CHAT_ITEMS));
	        setStatusText(message);
	    }, []);

    const inputPlaceholder = authSetup?.active && authSetup.prompt
        ? authSetup.prompt
        : spotifySetup?.active && spotifySetup.prompt
            ? spotifySetup.prompt
            : "Say something to awake Sonex.";
    const inputMask = authSetup?.active && authSetup.mask
        ? "*"
        : spotifySetup?.active && spotifySetup.mask
            ? "*"
            : undefined;
	    const onEvent = React.useCallback((evt: ServerEvent) => {
	        switch (evt.type) {
            case "chat":
                setChatItems((prev) => trimList([...prev, {role: evt.role, content: evt.text}], MAX_CHAT_ITEMS));
                break;
            case "activity":
                setActivityItems((prev) => upsertActivity(prev, evt));
                break;
            case "status":
                setStatusText(evt.message);
                if (typeof evt.elapsed_ms === "number") {
                    setElapsed(formatElapsed(evt.elapsed_ms));
                }
                if (typeof evt.tokens === "number") {
                    setTokens(`${evt.tokens} tokens`);
                }
                break;
            case "queue":
                setQueueItems(evt.tracks);
                break;
            case "search_results": {
                setSearchItems(evt.tracks);
                const first = evt.tracks[0];
                if (first) {
                    setPlayer({
                        name: first.title || first.name || "-",
                        artist: first.artist || "-",
                        album: first.album || "-",
                        duration_ms: first.duration_ms || 0,
                        progress_ms: 0,
                        is_playing: false,
                    });
                    setCoverUrl(first.album_cover_url ?? null);
                }
                break;
            }
            case "player":
                setPlayer(evt.state);
                if (evt.state.is_playing) {
                    setHasPlaybackIntent(true);
                    if (!manualLayoutOverride) {
                        setLayoutMode("full");
                    }
                }
                break;
	            case "cover":
	                setCoverUrl(evt.url);
	                break;
	            case "error":
	                showError(evt.message, evt.detail, false);
	                break;
            case "confirm":
                setConfirm({
                    id: evt.id,
                    tool_name: evt.tool_name,
                    tool_args: evt.tool_args,
                    message: evt.message || `Confirm ${evt.tool_name}`,
                    choices: evt.choices && evt.choices.length > 0 ? evt.choices : DEFAULT_CONFIRM_CHOICES,
                });
                setConfirmIndex(0);
                break;
            case "spotify_setup":
                setSpotifySetup({
                    step: evt.step,
                    title: evt.title,
                    message: evt.message,
                    prompt: evt.prompt,
                    mask: evt.mask,
                    active: evt.active !== false,
                });
                setStatusText(evt.title);
                break;
            case "auth_setup":
                setAuthSetup({
                    provider: evt.provider,
                    step: evt.step,
                    title: evt.title,
                    message: evt.message,
                    prompt: evt.prompt,
                    mask: evt.mask,
                    active: evt.active !== false,
                    methods: evt.methods,
                });
                setStatusText(evt.title);
                break;
        }
	    }, [manualLayoutOverride, showError]);

	    const {send} = useSonexSocket({
	        url: wsUrl,
	        onEvent,
	        onClientError: (message, detail) => showError(message, detail),
	    });

    const submitInput = React.useCallback((value: string) => {
        const text = value.trim();
        if (!text) return;

        const command = matchingSlashCommand(text);
        const suggestions = slashCommandSuggestions(text);
        if (!authSetup?.active && !spotifySetup?.active && text.startsWith("/") && !command) {
            const first = selectedSlashCommand ?? suggestions[0];
            if (first) {
                setInput(completeSlashCommand(first));
                setSlashIndex(0);
                setSlashMenuDismissedFor(null);
            }
            return;
        }

        if (
            !authSetup?.active &&
            !spotifySetup?.active &&
            command?.needsArgument &&
            !hasSlashCommandArguments(text)
        ) {
            setInput(completeSlashCommand(command));
            setSlashMenuDismissedFor(null);
            return;
        }

        setInput("");
        setSlashMenuDismissedFor(null);
        if (spotifySetup?.active) {
            send({type: "setup_input", value: text});
        } else if (authSetup?.active) {
            send({type: "auth_setup_input", value: text});
        } else {
            send({type: "user_input", text});
        }
    }, [authSetup?.active, selectedSlashCommand, send, spotifySetup?.active]);

    useInput((inputKey, key) => {
        if (!isSlashMenuActive || !selectedSlashCommand) return;

        if (key.upArrow) {
            setSlashIndex((prev) => (prev - 1 + slashSuggestions.length) % slashSuggestions.length);
        } else if (key.downArrow) {
            setSlashIndex((prev) => (prev + 1) % slashSuggestions.length);
        } else if (key.tab || inputKey === "\t") {
            setInput(completeSlashCommand(selectedSlashCommand));
            setSlashMenuDismissedFor(null);
        } else if (key.return) {
            const command = matchingSlashCommand(input);
            if (!command || (command.needsArgument && !hasSlashCommandArguments(input))) {
                setInput(completeSlashCommand(selectedSlashCommand));
                setSlashMenuDismissedFor(null);
            }
        } else if (key.escape) {
            setSlashMenuDismissedFor(input);
        }
    }, {isActive: isSlashMenuActive});

    useInput((inputKey, key) => {
        if (!confirm) return;

        if (key.upArrow) {
            setConfirmIndex((prev) => Math.max(0, prev - 1));
        } else if (key.downArrow) {
            setConfirmIndex((prev) => Math.min(confirm.choices.length - 1, prev + 1));
        } else if (key.return) {
            send({
                type: "confirm_result",
                id: confirm.id,
                decision: confirm.choices[confirmIndex]?.value ?? "allow_once",
            });
            setConfirm(null);
        } else if (key.escape) {
            send({type: "confirm_result", id: confirm.id, decision: "deny"});
            setConfirm(null);
        }
    }, {isActive: Boolean(confirm) && rawModeAvailable});

    useInput((inputKey, key) => {
        if (!player.is_playing || confirm || isSlashMenuActive) return;

        if (key.tab || inputKey === "\t") {
            setManualLayoutOverride(true);
            setLayoutMode((prev) => prev === "compact" ? "full" : "compact");
        }
    }, {isActive: rawModeAvailable && !confirm && !isSlashMenuActive});

    if (layoutMode === "compact") {
        return (
            <CompactShell
                input={input}
                setInput={updateInput}
                onSubmit={submitInput}
                inputPlaceholder={inputPlaceholder}
                inputMask={inputMask}
                inputFocus={!confirm && rawModeAvailable}
                chatItems={chatItems}
                statusText={statusText}
                confirm={confirm}
                confirmIndex={confirmIndex}
                spotifySetup={spotifySetup}
                authSetup={authSetup}
                player={player}
                coverUrl={coverUrl}
                showPlayer={hasPlaybackIntent && Boolean(player.is_playing)}
                slashSuggestions={slashSuggestions}
                slashIndex={slashIndex}
            />
        );
    }

    return (
        <FullShell
            input={input}
            setInput={updateInput}
            onSubmit={submitInput}
            inputPlaceholder={inputPlaceholder}
            inputMask={inputMask}
            inputFocus={!confirm && rawModeAvailable}
            chatItems={chatItems}
            activityItems={activityItems}
            queueItems={queueItems}
            searchItems={searchItems}
            player={player}
            statusText={statusText}
            elapsed={elapsed}
            tokens={tokens}
            coverUrl={coverUrl}
            confirm={confirm}
            confirmIndex={confirmIndex}
            spotifySetup={spotifySetup}
            authSetup={authSetup}
            slashSuggestions={slashSuggestions}
            slashIndex={slashIndex}
        />
    );
};

render(<App/>);

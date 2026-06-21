import type { ConfirmChoice, SlashCommandSuggestion } from './types.js';

export const wsUrl = process.env.SONEX_WS_URL ?? "ws://localhost:9001/ws";

export const APP_VERSION = "1.0.1";
export const FALLBACK_MODEL_NAME = "gpt-5.5";
export const BORDER_BLUE = "#3b82f6";
export const BORDER_BLUE_SOFT = "#9fd9ff";
export const APP_TIP_PLACEHOLDER = "Tips: try /random for a free play.";
export const MAX_CHAT_ITEMS = 80;
export const MAX_ACTIVITY_ITEMS = 80;
export const DEFAULT_CONFIRM_CHOICES: ConfirmChoice[] = [
    { value: "allow_once", label: "Yes" },
    { value: "deny", label: "No" },
];
export const MAX_VISIBLE_SLASH_COMMANDS = 4;
export const MAX_VISIBLE_MODEL_CHOICES = 3;
export const SLASH_COMMANDS: SlashCommandSuggestion[] = [
    { name: "bye", usage: "/bye", description: "save session and exit", needsArgument: false, aliases: ["exit"] },
    { name: "help", usage: "/help", description: "show available commands", needsArgument: false },
    { name: "keymap", usage: "/keymap [on|off|toggle|status]", description: "toggle mini-player playback shortcuts", needsArgument: false },
    { name: "lang", usage: "/lang", description: "choose the TUI display language", needsArgument: false },
    { name: "logout", usage: "/logout", description: "log out current LLM provider and exit", needsArgument: false },
    { name: "model", usage: "/model", description: "switch active model", needsArgument: false },
    { name: "player", usage: "/player", description: "choose playback backend from a panel", needsArgument: false },
    { name: "playlist", usage: "/playlist [name]|save [name]", description: "browse or save playlists", needsArgument: false },
    { name: "queue", usage: "/queue", description: "show playback queue", needsArgument: false },
    { name: "quit", usage: "/quit", description: "save session and exit", needsArgument: false },
    { name: "random", usage: "/random", description: "play from recent songs", needsArgument: false },
    { name: "recommend", usage: "/recommend", description: "recommend songs of preferred music taste", needsArgument: true },
    { name: "resume", usage: "/resume", description: "resume current playback", needsArgument: false },
    { name: "setup", usage: "/setup", description: "configure a music provider", needsArgument: true },
    { name: "spotify", usage: "/spotify [off]", description: "enter or exit session-only Spotify mode", needsArgument: false },
].sort((a, b) => a.name.localeCompare(b.name));
export const API_NOT_RUNNING_MESSAGE = "Sonex API is not running";
export const API_NOT_RUNNING_DETAIL = "Start with `sonex`, or run `sonex api` before `sonex tui`.";
export const CHAT_HEADER_ROWS = 2;
export const MIN_CHAT_VIEWPORT_ROWS = 1;

type MascotSegment = {
    text: string;
    fg?: string; // 上半部分颜色
    bg?: string; // 下半部分颜色
};

export const SONEX_MASCOT: MascotSegment[][] = [
    [
        { text: "    " },
        { text: "▄", fg: "#000000" },
        { text: "▀▀▀▀▀", fg: "#000000", bg: "#f4f1f3" },
        { text: "▄", fg: "#000000" },
    ],
    [
        { text: "  " },
        { text: "▄", fg: "#000000" },
        { text: "▀", fg: "#000000", bg: "#f4f1f3" },
        { text: "▀", fg: "#f4f1f3", bg: "#000000" },
        { text: "▀▀▀▀▀", fg: "#000000", bg: "#9fd9ff" },
        { text: "▀", fg: "#f4f1f3", bg: "#000000" },
        { text: "▄", fg: "#000000" },
    ],
    [
        { text: "  " },
        { text: "█", fg: "#000000" },
        { text: "▀", fg: "#f4f1f3", bg: "#000000" },
        { text: "▀", fg: "#000000", bg: "#9fd9ff" },
        { text: "██████", fg: "#9fd9ff" },
        { text: "▀", fg: "#4b5161", bg: "#9fd9ff" },
        { text: "▄", fg: "#4b5161" },
    ],
    [
        { text: " " },
        { text: "█", fg: "#000000" },
        { text: "██", fg: "#f4f1f3" },
        { text: "█", fg: "#000000" },
        { text: "██", fg: "#9fd9ff" },
        { text: "█", fg: "#000000" },
        { text: "██", fg: "#9fd9ff" },
        { text: "█", fg: "#000000" },
        { text: "█", fg: "#9fd9ff" },
        { text: "█", fg: "#4b5161" },
    ],
    [
        { text: " " },
        { text: "▀", fg: "#000000" },
        { text: "▀▀", fg: "#f4f1f3", bg: "#000000" },
        { text: "▀", fg: "#000000", bg: "#9fd9ff" },
        { text: "███████", fg: "#9fd9ff" },
        { text: "▀", fg: "#4b5161" },
    ],
    [
        { text: "  " },
        { text: "▄", fg: "#4b5161" },
        { text: "▀", fg: "#4b5161", bg: "#9fd9ff" },
        { text: "██████", fg: "#9fd9ff" },
        { text: "█", fg: "#9fd9ff" },
        { text: "▀", fg: "#9fd9ff" },
    ],
    [
        { text: "  " },
        { text: "▀", fg: "#4b5161" },
        { text: "▀", fg: "#9fd9ff" },
        { text: "▀", fg: "#9fd9ff" },
        { text: "█████", fg: "#9fd9ff" },
        { text: "▀", fg: "#9fd9ff" },
    ],
];

export const SONEX_MASCOT_MICRO: MascotSegment[][] = [
    [
        { text: "█", fg: "#9fd9ff" },
        { text: "▀", fg: "#9fd9ff", bg: "#000000" },
        { text: "██", fg: "#9fd9ff" },
        { text: "▀", fg: "#9fd9ff", bg: "#000000" },
        { text: "█", fg: "#9fd9ff" },
    ],
];

import type { ConfirmChoice, SlashCommandSuggestion } from './types.js';
import { resolveUiTheme, type UiThemeId } from './ui-theme.js';

export const wsUrl = process.env.SONEX_WS_URL ?? "ws://localhost:9001/ws";

export const APP_VERSION = "0.1.0-alpha.4";
export const FALLBACK_MODEL_NAME = "gpt-5.5";
export let BORDER_BLUE = "#3b82f6";
export let BORDER_BLUE_SOFT = "#9fd9ff";
export let TOOL_NAVY = "#182e66";
export let TOOL_VALUE = "#ffffff";
export const SPOTIFY_GREEN = "#1db954";
export let PANEL_BACKGROUND = "#48273e";
export let PANEL_TITLE = "#c8a6ff";
export let PANEL_PRIMARY = "#fff4f6";
export let PANEL_SECONDARY = "#808791";
export let PLAYER_SECONDARY = "#bf98a7";
export let PLAYER_PAUSED = "#7f5d6b";

export function applyUiTheme(theme: UiThemeId): void {
    const tokens = resolveUiTheme(theme);
    BORDER_BLUE = tokens.accent;
    BORDER_BLUE_SOFT = tokens.accentSoft;
    TOOL_NAVY = tokens.toolBackground;
    TOOL_VALUE = tokens.primary;
    PANEL_BACKGROUND = tokens.panelBackground;
    PANEL_TITLE = tokens.panelTitle;
    PANEL_PRIMARY = tokens.primary;
    PANEL_SECONDARY = tokens.secondary;
    PLAYER_SECONDARY = tokens.playerSecondary;
    PLAYER_PAUSED = tokens.playerPaused;
}
export const APP_TIP_PLACEHOLDER = "Tip: use /random to play a recent song.";
export const MAX_ACTIVITY_ITEMS = 80;
export const DEFAULT_CONFIRM_CHOICES: ConfirmChoice[] = [
    { value: "allow_once", label: "Yes" },
    { value: "deny", label: "No" },
];
export const MAX_VISIBLE_SLASH_COMMANDS = 4;
export const MAX_VISIBLE_MODEL_CHOICES = 4;
export const SLASH_COMMANDS: SlashCommandSuggestion[] = [
    { name: "bye", usage: "/bye", description: "save and exit", needsArgument: false },
    { name: "extension", usage: "/extension", description: "check and manage music extensions", needsArgument: false },
    { name: "exit", usage: "/exit", description: "save and exit", needsArgument: false },
    { name: "help", usage: "/help", description: "show commands", needsArgument: false },
    { name: "info", usage: "/info", description: "show runtime info", needsArgument: false },
    { name: "lang", usage: "/lang", description: "choose display language", needsArgument: false, enabled: false },
    { name: "login", usage: "/login", description: "connect or switch LLM provider", needsArgument: false },
    { name: "logout", usage: "/logout", description: "sign out and exit", needsArgument: false },
    { name: "memory", usage: "/memory", description: "configure long-term memory", needsArgument: false },
    { name: "model", usage: "/model", description: "switch active model", needsArgument: false },
    { name: "playlist", usage: "/playlist [name]|save [name]", description: "browse or save playlists", needsArgument: false },
    { name: "proxy", usage: "/proxy", description: "configure outbound proxy routing", needsArgument: false },
    { name: "queue", usage: "/queue", description: "show playback queue", needsArgument: false },
    { name: "random", usage: "/random", description: "play a recent song", needsArgument: false },
    { name: "recommend", usage: "/recommend", description: "recommend songs", needsArgument: false },
    { name: "resume", usage: "/resume", description: "resume playback", needsArgument: false },
    { name: "sandbox", usage: "/sandbox", description: "check Agent Bash sandbox", needsArgument: false },
    { name: "settings", usage: "/settings", description: "configure Sonex settings", needsArgument: false, aliases: ["setting"] },
    { name: "spotify", usage: "/spotify", description: "toggle Spotify mode", needsArgument: false },
    { name: "theme", usage: "/theme", description: "choose interface theme", needsArgument: false },
].sort((a, b) => a.name.localeCompare(b.name));
export const API_NOT_RUNNING_MESSAGE = "Sonex API is not running";
export const API_NOT_RUNNING_DETAIL = "Start with `sonex`, or run `sonex api` before `sonex tui`.";
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

import { BORDER_BLUE, SPOTIFY_GREEN, TOOL_NAVY } from './constants.js';
import type { ChatTheme } from './types.js';

export type AgentChatThemeTokens = {
    accent: string;
    strongText: string;
    highlightBackground: string;
    codeBackground: string;
    linkText: string;
};

const DEFAULT_AGENT_CHAT_THEME: AgentChatThemeTokens = {
    accent: BORDER_BLUE,
    strongText: BORDER_BLUE,
    highlightBackground: TOOL_NAVY,
    codeBackground: '#252933',
    linkText: '#9fd9ff',
};

const SPOTIFY_AGENT_CHAT_THEME: AgentChatThemeTokens = {
    accent: SPOTIFY_GREEN,
    strongText: SPOTIFY_GREEN,
    highlightBackground: '#0b3d20',
    codeBackground: '#252933',
    linkText: '#73d998',
};

export function resolveAgentChatTheme(theme: ChatTheme | null): AgentChatThemeTokens {
    return theme === 'spotify' ? SPOTIFY_AGENT_CHAT_THEME : DEFAULT_AGENT_CHAT_THEME;
}

import type { ChatTheme } from './types.js';
import { resolveUiTheme, type UiThemeId } from './ui-theme.js';

export type AgentChatThemeTokens = {
    accent: string;
    strongText: string;
    highlightBackground: string;
    codeBackground: string;
    linkText: string;
};

export function resolveAgentChatTheme(_theme: ChatTheme | null, uiTheme?: UiThemeId | null): AgentChatThemeTokens {
    const tokens = resolveUiTheme(uiTheme);
    return {
        accent: tokens.accent,
        strongText: tokens.accent,
        highlightBackground: tokens.toolBackground,
        codeBackground: tokens.codeBackground,
        linkText: tokens.link,
    };
}

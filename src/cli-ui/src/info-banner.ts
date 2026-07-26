import { homedir } from 'node:os';

import type { AuthRuntimeState, ChatItem, ChatMessageItem, ChatTranscriptMessage, InfoBannerItem } from './types.js';

export function formatWorkingDirectory(cwd: string, homeDirectory: string = homedir()): string {
    if (!homeDirectory) return cwd;

    const windowsStyle = /^[A-Za-z]:[\\/]/.test(cwd) || cwd.includes("\\");
    const normalizeForComparison = (value: string): string => (
        windowsStyle ? value.replaceAll("/", "\\").toLowerCase() : value.replaceAll("\\", "/")
    );
    const separator = windowsStyle ? "\\" : "/";
    const normalizedCwd = normalizeForComparison(cwd).replace(/[\\/]+$/, "");
    const normalizedHome = normalizeForComparison(homeDirectory).replace(/[\\/]+$/, "");

    if (normalizedCwd === normalizedHome) return "~";
    if (!normalizedCwd.startsWith(`${normalizedHome}${separator}`)) return cwd;

    const relative = cwd.slice(homeDirectory.replace(/[\\/]+$/, "").length).replace(/^[\\/]+/, "");
    return relative ? `~${separator}${relative}` : "~";
}

export function createInfoBannerItem(
    authState: AuthRuntimeState,
    cwd: string,
    sessionId: string | null,
): InfoBannerItem {
    return {
        type: "info_banner",
        authState: { ...authState },
        cwd,
        sessionId,
    };
}

export function isChatMessageItem(item: ChatItem): item is ChatMessageItem {
    return item.type === "message";
}

export function chatMessagesForTranscript(items: ChatItem[]): ChatTranscriptMessage[] {
    return items.filter(isChatMessageItem).map(({ role, content, theme }) => ({
        role,
        content,
        ...(theme == null ? {} : { theme }),
    }));
}

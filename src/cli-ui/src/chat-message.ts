import stringWidth from 'string-width';

import { BORDER_BLUE, SPOTIFY_GREEN } from './constants.js';
import type { ChatRole, ChatTheme, ChatTone } from './types.js';

export const CHAT_USER_MARKER_COLOR = "#808791";
export const CHAT_SYSTEM_MARKER_COLOR = "#c8a6ff";
export const CHAT_WARNING_MARKER_COLOR = "#d4a72c";
export const CHAT_ERROR_MARKER_COLOR = "#ef4444";

export function wrapChatMessageContent(content: string, width: number): string[] {
    const boundedWidth = Math.max(1, Math.floor(width));
    const physicalLines: string[] = [];

    for (const logicalLine of content.split("\n")) {
        if (logicalLine.length === 0) {
            physicalLines.push("");
            continue;
        }

        let line = "";
        let lineWidth = 0;
        for (const char of Array.from(logicalLine)) {
            const charWidth = stringWidth(char);
            if (line.length > 0 && lineWidth + charWidth > boundedWidth) {
                physicalLines.push(line);
                line = "";
                lineWidth = 0;
            }
            if (line.length === 0 && charWidth > boundedWidth) {
                physicalLines.push(char);
                continue;
            }
            line += char;
            lineWidth += charWidth;
        }
        if (line.length > 0) {
            physicalLines.push(line);
        }
    }

    return physicalLines.length > 0 ? physicalLines : [""];
}

export function resolveChatSubject(
    role: ChatRole,
    tone: ChatTone | null,
): "User" | "Agent" | "System" | "Warning" | "Caution" {
    if (role === "user") return "User";
    if (tone === "error") return "Caution";
    if (tone === "warning") return "Warning";
    if (tone === "system") return "System";
    return "Agent";
}

export function resolveChatMarkerColor(
    role: ChatRole,
    theme: ChatTheme | null,
    tone: ChatTone | null,
): string {
    if (role === "user") return CHAT_USER_MARKER_COLOR;
    if (tone === "error") return CHAT_ERROR_MARKER_COLOR;
    if (tone === "warning") return CHAT_WARNING_MARKER_COLOR;
    if (tone === "system") return CHAT_SYSTEM_MARKER_COLOR;
    if (theme === "spotify") return SPOTIFY_GREEN;
    return BORDER_BLUE;
}

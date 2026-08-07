import stringWidth from 'string-width';

import { BORDER_BLUE, SPOTIFY_GREEN } from './constants.js';
import type { ChatRole, ChatSegment, ChatTheme, ChatTone } from './types.js';

export const CHAT_USER_MARKER_COLOR = "#808791";
export const CHAT_SYSTEM_MARKER_COLOR = "#c8a6ff";
export const CHAT_WARNING_MARKER_COLOR = "#d4a72c";
export const CHAT_ERROR_MARKER_COLOR = "#ef4444";
export const CHAT_MESSAGE_TEXT_COLOR = "#ffffff";

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

export function wrapChatMessageSegments(
    segments: ChatSegment[],
    width: number,
): ChatSegment[][] {
    const boundedWidth = Math.max(1, Math.floor(width));
    const lines: ChatSegment[][] = [[]];
    let lineWidth = 0;

    const append = (text: string, style: ChatSegment["style"]) => {
        if (!text) return;
        const line = lines[lines.length - 1]!;
        const previous = line[line.length - 1];
        if (previous?.style === style) {
            previous.text += text;
        } else {
            line.push({ text, style });
        }
    };

    for (const segment of segments) {
        for (const character of Array.from(segment.text)) {
            if (character === "\n") {
                lines.push([]);
                lineWidth = 0;
                continue;
            }
            const characterWidth = stringWidth(character);
            if (lineWidth > 0 && lineWidth + characterWidth > boundedWidth) {
                lines.push([]);
                lineWidth = 0;
            }
            append(character, segment.style);
            lineWidth += characterWidth;
        }
    }

    return lines.length > 0 ? lines : [[]];
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

export function resolveChatContentColor(role: ChatRole, tone: ChatTone | null): string {
    if (role === "user") return CHAT_MESSAGE_TEXT_COLOR;
    if (tone === "error") return CHAT_ERROR_MARKER_COLOR;
    if (tone === "warning") return CHAT_WARNING_MARKER_COLOR;
    return CHAT_MESSAGE_TEXT_COLOR;
}

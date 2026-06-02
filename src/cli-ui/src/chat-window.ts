import {CHAT_HEADER_ROWS, ESTIMATED_CHAT_WRAP_WIDTH, MIN_CHAT_VIEWPORT_ROWS} from './constants.js';
import type {ChatItem, VisibleChatWindow} from './types.js';

export function trimList<T>(items: T[], limit: number): T[] {
    return items.slice(Math.max(0, items.length - limit));
}

export function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}

function estimateChatItemRows(item: ChatItem): number {
    const contentRows = item.content.split("\n").reduce((rows, line) => {
        return rows + Math.max(1, Math.ceil(line.length / ESTIMATED_CHAT_WRAP_WIDTH));
    }, 0);
    return contentRows + 1;
}

export function getVisibleChatWindow(items: ChatItem[], viewportRows: number, scrollOffset: number): VisibleChatWindow {
    if (items.length === 0) {
        return {items: [], hasHiddenAbove: false, hasHiddenBelow: false, maxScrollOffset: 0};
    }

    const contentRows = Math.max(MIN_CHAT_VIEWPORT_ROWS, viewportRows - CHAT_HEADER_ROWS);
    const maxScrollOffset = Math.max(0, items.length - 1);
    const boundedOffset = clamp(scrollOffset, 0, maxScrollOffset);
    const endExclusive = Math.max(1, items.length - boundedOffset);
    let startIndex = endExclusive;
    let usedRows = 0;

    while (startIndex > 0) {
        const nextRows = estimateChatItemRows(items[startIndex - 1]);
        if (usedRows > 0 && usedRows + nextRows > contentRows) {
            break;
        }
        usedRows += nextRows;
        startIndex -= 1;
        if (usedRows >= contentRows) {
            break;
        }
    }

    return {
        items: items.slice(startIndex, endExclusive),
        hasHiddenAbove: startIndex > 0,
        hasHiddenBelow: endExclusive < items.length,
        maxScrollOffset,
    };
}

import stringWidth from 'string-width';
import { CHAT_HEADER_ROWS, MIN_CHAT_VIEWPORT_ROWS } from './constants.js';
import type { ChatHeaderVariant } from './layout.js';
import type { ChatItem, VisibleChatWindow } from './types.js';

/**
 * Coordinates the trim list operation for the CLI UI runtime.
 *
 * @param items Input value used by the trim list operation.
 * @param limit Input value used by the trim list operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function trimList<T>(items: T[], limit: number): T[] {
    return items.slice(Math.max(0, items.length - limit));
}

/**
 * Coordinates the clamp operation for the CLI UI runtime.
 *
 * @param value Input value used by the clamp operation.
 * @param min Input value used by the clamp operation.
 * @param max Input value used by the clamp operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}

/**
 * Coordinates the estimate chat item rows operation for the CLI UI runtime.
 *
 * @param item Input value used by the estimate chat item rows operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function estimateChatItemRows(item: ChatItem, wrapWidth: number, headerVariant: ChatHeaderVariant): number {
    if (item.type === "info_banner") {
        return headerVariant === "compact" ? 6 : 9;
    }
    const boundedWrapWidth = Math.max(1, wrapWidth);
    const contentRows = item.content.split("\n").reduce((rows, line) => {
        return rows + Math.max(1, Math.ceil(stringWidth(line) / boundedWrapWidth));
    }, 0);
    return contentRows + 1;
}

/**
 * Coordinates the get visible chat window operation for the CLI UI runtime.
 *
 * @param items Input value used by the get visible chat window operation.
 * @param viewportRows Input value used by the get visible chat window operation.
 * @param scrollOffset Input value used by the get visible chat window operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function getVisibleChatWindow(
    items: ChatItem[],
    viewportRows: number,
    scrollOffset: number,
    wrapWidth: number,
    headerVariant: ChatHeaderVariant = "full",
): VisibleChatWindow {
    if (items.length === 0) {
        return { items: [], hasHiddenAbove: false, hasHiddenBelow: false, maxScrollOffset: 0 };
    }

    const contentRows = Math.max(MIN_CHAT_VIEWPORT_ROWS, viewportRows - CHAT_HEADER_ROWS);
    const maxScrollOffset = Math.max(0, items.length - 1);
    const boundedOffset = clamp(scrollOffset, 0, maxScrollOffset);
    const endExclusive = Math.max(1, items.length - boundedOffset);
    let startIndex = endExclusive;
    let usedRows = 0;

    while (startIndex > 0) {
        const nextRows = estimateChatItemRows(items[startIndex - 1], wrapWidth, headerVariant);
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

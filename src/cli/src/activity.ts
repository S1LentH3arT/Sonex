import { MAX_ACTIVITY_ITEMS } from './constants.js';
import { trimList } from './list.js';
import type { ActivityItem } from './types.js';

/**
 * Coordinates the upsert activity operation for the CLI UI runtime.
 *
 * @param items Input value used by the upsert activity operation.
 * @param item Input value used by the upsert activity operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function upsertActivity(items: ActivityItem[], item: ActivityItem): ActivityItem[] {
    const index = items.findIndex((existing) => existing.id === item.id);
    if (index === -1) {
        return trimList([...items, item], MAX_ACTIVITY_ITEMS);
    }

    const next = [...items];
    next[index] = { ...next[index], ...item };
    return trimList(next, MAX_ACTIVITY_ITEMS);
}

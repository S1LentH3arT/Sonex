import {MAX_ACTIVITY_ITEMS} from './constants.js';
import {trimList} from './chat-window.js';
import type {ActivityItem} from './types.js';

export function upsertActivity(items: ActivityItem[], item: ActivityItem): ActivityItem[] {
    const index = items.findIndex((existing) => existing.id === item.id);
    if (index === -1) {
        return trimList([...items, item], MAX_ACTIVITY_ITEMS);
    }

    const next = [...items];
    next[index] = {...next[index], ...item};
    return trimList(next, MAX_ACTIVITY_ITEMS);
}

export function buildErrorActivity(message: string, detail?: string | null): ActivityItem {
    return {
        id: `error_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        kind: "error",
        title: message,
        detail,
        status: "error",
        timestamp: Date.now(),
    };
}

import type { ChatMessageItem } from './types.js';

export const TEXT_STREAM_INTERVAL_MS = 16;
export const TEXT_STREAM_TARGET_FRAMES = 60;

export const textStreamUnits = (text: string): string[] => Array.from(text);

export const nextTextStreamOffset = (current: number, total: number): number => {
    const normalizedTotal = Math.max(0, Math.floor(total));
    const normalizedCurrent = Math.min(normalizedTotal, Math.max(0, Math.floor(current)));
    if (normalizedCurrent >= normalizedTotal) return normalizedTotal;

    const chunkSize = Math.max(1, Math.ceil(normalizedTotal / TEXT_STREAM_TARGET_FRAMES));
    return Math.min(normalizedTotal, normalizedCurrent + chunkSize);
};

export const streamedChatMessage = (
    item: ChatMessageItem,
    units: string[],
    visibleUnitCount: number,
): ChatMessageItem => ({
    ...item,
    content: units.slice(0, Math.max(0, visibleUnitCount)).join(''),
    segments: undefined,
    document: undefined,
});

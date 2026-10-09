import type { SessionTokenUsage } from './types.js';

export const TOKEN_USAGE_ANIMATION_INTERVAL_MS = 16;

const normalizeTokenCount = (value: number): number => Math.max(0, Math.floor(value));

export const nextAnimatedTokenCount = (current: number, target: number): number => {
    const normalizedCurrent = normalizeTokenCount(current);
    const normalizedTarget = normalizeTokenCount(target);
    if (normalizedCurrent >= normalizedTarget) return normalizedTarget;

    const remaining = normalizedTarget - normalizedCurrent;
    return Math.min(normalizedTarget, normalizedCurrent + Math.max(1, Math.ceil(remaining / 4)));
};

export const nextAnimatedTokenUsage = (
    current: SessionTokenUsage,
    target: SessionTokenUsage,
): SessionTokenUsage => ({
    inputTokens: nextAnimatedTokenCount(current.inputTokens, target.inputTokens),
    outputTokens: nextAnimatedTokenCount(current.outputTokens, target.outputTokens),
});

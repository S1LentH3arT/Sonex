import type { ActivityItem } from './types.js';
import type { UiLanguage } from './types.js';

export const LAUNCH_PREPARING_INTERVAL_MS = 1000;

/**
 * Coordinates the launch preparing text operation for the CLI UI runtime.
 *
 * @param frame Input value used by the launch preparing text operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function launchPreparingText(frame: number, language: UiLanguage = "en"): string {
    const dotCount = (Math.max(0, frame) % 3) + 1;
    const base = language === "zh-CN" ? "播放准备中" : "Launch preparing";
    return `${base}${'.'.repeat(dotCount)}`;
}

/**
 * Coordinates the should start launch preparing operation for the CLI UI runtime.
 *
 * @param activity Input value used by the should start launch preparing operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function shouldStartLaunchPreparing(activity: Pick<ActivityItem, 'kind' | 'title' | 'status'>): boolean {
    const launchPreparingTitles = new Set([
        'Searching Spotify',
        'Searching online audio',
        'Caching online audio',
        'Searching YouTube',
        'Caching YouTube audio',
    ]);
    return activity.kind === 'tool'
        && activity.status === 'pending'
        && launchPreparingTitles.has(activity.title);
}

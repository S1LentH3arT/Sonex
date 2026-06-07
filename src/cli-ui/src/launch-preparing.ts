import type {ActivityItem} from './types.js';

export const LAUNCH_PREPARING_INTERVAL_MS = 1000;

export function launchPreparingText(frame: number): string {
    const dotCount = (Math.max(0, frame) % 3) + 1;
    return `Launch preparing${'.'.repeat(dotCount)}`;
}

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

import type {ActivityItem} from './types.js';

export const LAUNCH_PREPARING_INTERVAL_MS = 80;

export function launchPreparingText(frame: number): string {
    const dotCount = (Math.max(0, frame) % 3) + 1;
    return `Launch preparing${'.'.repeat(dotCount)}`;
}

export function shouldStartLaunchPreparing(activity: Pick<ActivityItem, 'kind' | 'title' | 'status'>): boolean {
    return activity.kind === 'tool'
        && activity.status === 'pending'
        && (activity.title === 'Searching YouTube' || activity.title === 'Caching YouTube audio');
}

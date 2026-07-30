export function trimList<T>(items: T[], limit: number): T[] {
    return items.slice(Math.max(0, items.length - limit));
}

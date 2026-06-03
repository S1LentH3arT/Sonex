export function formatElapsed(ms?: number | null): string {
    if (!ms) return "00m 00s";
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
    const seconds = (totalSeconds % 60).toString().padStart(2, "0");
    return `${minutes}m ${seconds}s`;
}

export function formatDuration(ms: number): string {
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = (totalSeconds % 60).toString().padStart(2, "0");
    return `${minutes}:${seconds}`;
}

export function buildProgressBar(progressMs: number, durationMs: number, width = 18): string {
    if (durationMs <= 0) return "─".repeat(width);
    const ratio = Math.min(1, Math.max(0, progressMs / durationMs));
    const exact = ratio * width;
    const filled = Math.floor(exact);
    if (filled >= width) return "━".repeat(width);
    const partial = exact - filled >= 0.5 ? "╸" : "";
    return "━".repeat(filled) + partial + "─".repeat(width - filled - partial.length);
}

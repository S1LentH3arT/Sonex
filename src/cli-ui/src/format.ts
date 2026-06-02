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
    const filled = Math.round(ratio * width);
    return "━".repeat(filled) + "─".repeat(width - filled);
}

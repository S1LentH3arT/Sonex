/**
 * Format elapsed.
 *
 * Coordinates the format elapsed operation for the CLI UI runtime.
 *
 * @param ms Input value used by the format elapsed operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function formatElapsed(ms?: number | null): string {
    if (!ms) return "00m 00s";
    /**
     * Defines the total seconds constant.
     *
     * Stores stable configuration or display data consumed by format.ts.
     */
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    /**
     * Defines the minutes constant.
     *
     * Stores stable configuration or display data consumed by format.ts.
     */
    const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
    /**
     * Defines the seconds constant.
     *
     * Stores stable configuration or display data consumed by format.ts.
     */
    const seconds = (totalSeconds % 60).toString().padStart(2, "0");
    return `${minutes}m ${seconds}s`;
}

/**
 * Format duration.
 *
 * Coordinates the format duration operation for the CLI UI runtime.
 *
 * @param ms Input value used by the format duration operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function formatDuration(ms: number): string {
    /**
     * Defines the total seconds constant.
     *
     * Stores stable configuration or display data consumed by format.ts.
     */
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    /**
     * Defines the minutes constant.
     *
     * Stores stable configuration or display data consumed by format.ts.
     */
    const minutes = Math.floor(totalSeconds / 60);
    /**
     * Defines the seconds constant.
     *
     * Stores stable configuration or display data consumed by format.ts.
     */
    const seconds = (totalSeconds % 60).toString().padStart(2, "0");
    return `${minutes}:${seconds}`;
}

/**
 * Build progress bar.
 *
 * Coordinates the build progress bar operation for the CLI UI runtime.
 *
 * @param progressMs Input value used by the build progress bar operation.
 * @param durationMs Input value used by the build progress bar operation.
 * @param width Input value used by the build progress bar operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function buildProgressBar(progressMs: number, durationMs: number, width = 18): string {
    if (durationMs <= 0) return "─".repeat(width);
    /**
     * Defines the ratio constant.
     *
     * Stores stable configuration or display data consumed by format.ts.
     */
    const ratio = Math.min(1, Math.max(0, progressMs / durationMs));
    /**
     * Defines the exact constant.
     *
     * Stores stable configuration or display data consumed by format.ts.
     */
    const exact = ratio * width;
    /**
     * Defines the filled constant.
     *
     * Stores stable configuration or display data consumed by format.ts.
     */
    const filled = Math.floor(exact);
    if (filled >= width) return "━".repeat(width);
    /**
     * Defines the partial constant.
     *
     * Stores stable configuration or display data consumed by format.ts.
     */
    const partial = exact - filled >= 0.5 ? "╸" : "";
    return "━".repeat(filled) + partial + "─".repeat(width - filled - partial.length);
}

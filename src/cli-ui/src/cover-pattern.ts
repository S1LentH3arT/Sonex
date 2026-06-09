export type CoverPatternPayload = {
    source_url: string;
    palette: string[];
    variants: Partial<Record<`${number}`, number[][]>>;
    source_hash?: string;
    generated_at?: number;
};

export type TerminalSpace = {
    columns: number | null;
    rows: number | null;
};

export type CoverPatternVariant = {
    size: number;
    grid: number[][];
};

export type CoverPatternVariantOptions = {
    maxSize?: number;
};

export type HalfBlockCell = {
    char: '▀';
    foreground: string;
    background: string;
};

/**
 * Coordinates the choose cover pattern variant operation for the CLI UI runtime.
 *
 * @param pattern Input value used by the choose cover pattern variant operation.
 * @param space Input value used by the choose cover pattern variant operation.
 * @param options Input value used by the choose cover pattern variant operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function chooseCoverPatternVariant(
    pattern: CoverPatternPayload | null,
    space: TerminalSpace,
    options: CoverPatternVariantOptions = {},
): CoverPatternVariant | null {
    if (!pattern || !space.columns || !space.rows) return null;

    const sizes = Object.keys(pattern.variants)
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && value > 0)
        .sort((left, right) => right - left);

    for (const size of sizes) {
        if (options.maxSize && size > options.maxSize) continue;
        const grid = pattern.variants[String(size) as `${number}`];
        if (!grid || grid.length !== size) continue;
        if (space.columns >= size && space.rows >= size / 2) {
            return { size, grid };
        }
    }
    return null;
}

/**
 * Coordinates the render cover pattern half blocks operation for the CLI UI runtime.
 *
 * @param grid Input value used by the render cover pattern half blocks operation.
 * @param palette Input value used by the render cover pattern half blocks operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function renderCoverPatternHalfBlocks(grid: number[][], palette: string[]): HalfBlockCell[][] {
    const rows: HalfBlockCell[][] = [];
    for (let y = 0; y < grid.length; y += 2) {
        const upper = grid[y] ?? [];
        const lower = grid[y + 1] ?? upper;
        rows.push(upper.map((upperIndex, x) => ({
            char: '▀',
            foreground: palette[upperIndex] ?? '#ffffff',
            background: palette[lower[x] ?? upperIndex] ?? '#000000',
        })));
    }
    return rows;
}

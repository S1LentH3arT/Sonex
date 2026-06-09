/**
 * Describes the cover pattern payload type.
 *
 * Documents the shape shared across cover-pattern.ts call sites.
 */
export type CoverPatternPayload = {
    source_url: string;
    palette: string[];
    variants: Partial<Record<32 | 48 | 64, number[][]>>;
    source_hash?: string;
    generated_at?: number;
};

/**
 * Describes the terminal space type.
 *
 * Documents the shape shared across cover-pattern.ts call sites.
 */
export type TerminalSpace = {
    columns: number | null;
    rows: number | null;
};

/**
 * Describes the cover pattern variant type.
 *
 * Documents the shape shared across cover-pattern.ts call sites.
 */
export type CoverPatternVariant = {
    size: 32 | 48 | 64;
    grid: number[][];
};

/**
 * Describes the cover pattern variant options type.
 *
 * Documents the shape shared across cover-pattern.ts call sites.
 */
export type CoverPatternVariantOptions = {
    maxSize?: 32 | 48 | 64;
};

/**
 * Describes the half block cell type.
 *
 * Documents the shape shared across cover-pattern.ts call sites.
 */
export type HalfBlockCell = {
    char: '▀';
    foreground: string;
    background: string;
};

/**
 * Defines the sizes constant.
 *
 * Stores stable configuration or display data consumed by cover-pattern.ts.
 */
const SIZES: Array<32 | 48 | 64> = [64, 48, 32];

/**
 * Choose cover pattern variant.
 *
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

    for (const size of SIZES) {
        if (options.maxSize && size > options.maxSize) continue;
        /**
         * Defines the grid constant.
         *
         * Stores stable configuration or display data consumed by cover-pattern.ts.
         */
        const grid = pattern.variants[size];
        if (!grid || grid.length !== size) continue;
        if (space.columns >= size && space.rows >= size / 2) {
            return { size, grid };
        }
    }
    return null;
}

/**
 * Render cover pattern half blocks.
 *
 * Coordinates the render cover pattern half blocks operation for the CLI UI runtime.
 *
 * @param grid Input value used by the render cover pattern half blocks operation.
 * @param palette Input value used by the render cover pattern half blocks operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function renderCoverPatternHalfBlocks(grid: number[][], palette: string[]): HalfBlockCell[][] {
    /**
     * Defines the rows constant.
     *
     * Stores stable configuration or display data consumed by cover-pattern.ts.
     */
    const rows: HalfBlockCell[][] = [];
    for (let y = 0; y < grid.length; y += 2) {
        /**
         * Defines the upper constant.
         *
         * Stores stable configuration or display data consumed by cover-pattern.ts.
         */
        const upper = grid[y] ?? [];
        /**
         * Defines the lower constant.
         *
         * Stores stable configuration or display data consumed by cover-pattern.ts.
         */
        const lower = grid[y + 1] ?? upper;
        rows.push(upper.map((upperIndex, x) => ({
            char: '▀',
            foreground: palette[upperIndex] ?? '#ffffff',
            background: palette[lower[x] ?? upperIndex] ?? '#000000',
        })));
    }
    return rows;
}

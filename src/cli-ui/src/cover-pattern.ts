export type CoverPatternPayload = {
    source_url: string;
    palette: string[];
    variants: Partial<Record<36 | 48 | 64, number[][]>>;
    source_hash?: string;
    generated_at?: number;
};

export type TerminalSpace = {
    columns: number | null;
    rows: number | null;
};

export type CoverPatternVariant = {
    size: 36 | 48 | 64;
    grid: number[][];
};

export type HalfBlockCell = {
    char: '▀';
    foreground: string;
    background: string;
};

const SIZES: Array<36 | 48 | 64> = [64, 48, 36];

export function chooseCoverPatternVariant(
    pattern: CoverPatternPayload | null,
    space: TerminalSpace,
): CoverPatternVariant | null {
    if (!pattern || !space.columns || !space.rows) return null;

    for (const size of SIZES) {
        const grid = pattern.variants[size];
        if (!grid || grid.length !== size) continue;
        if (space.columns >= size && space.rows >= size / 2) {
            return {size, grid};
        }
    }
    return null;
}

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

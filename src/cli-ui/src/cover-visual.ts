export type CoverVisualStatus = 'ready' | 'fallback';

export type CoverVisualModel = {
    status: CoverVisualStatus;
    seed: number;
    primary: string;
    secondary: string;
    accent: string;
    muted: string;
    blocks: string[][];
};

const FALLBACK_SEED = 0x5e9ec7;
const BLOCK_ROWS = 8;
const BLOCK_COLUMNS = 14;

/**
 * Coordinates the cover visual from source operation for the CLI UI runtime.
 *
 * @param source Input value used by the cover visual from source operation.
 * @param failed Input value used by the cover visual from source operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function coverVisualFromSource(source: string | null, failed = false): CoverVisualModel {
    const normalized = source?.trim() || '';
    const seed = normalized && !failed ? hashSource(normalized) : FALLBACK_SEED;
    const palette = paletteFromSeed(seed);

    return {
        status: normalized && !failed ? 'ready' : 'fallback',
        seed,
        ...palette,
        blocks: buildBlockMatrix(seed, palette),
    };
}

/**
 * Coordinates the rhythm frame for playback operation for the CLI UI runtime.
 *
 * @param isPlaying Input value used by the rhythm frame for playback operation.
 * @param progressMs Input value used by the rhythm frame for playback operation.
 * @param seed Input value used by the rhythm frame for playback operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function rhythmFrameForPlayback(isPlaying: boolean, progressMs: number, seed: number): number {
    if (!isPlaying) {
        return 0;
    }

    const phase = Math.floor(Math.max(0, progressMs) / 700);
    return (phase + (seed % 4)) % 4;
}

/**
 * Coordinates the hash source operation for the CLI UI runtime.
 *
 * @param source Input value used by the hash source operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function hashSource(source: string): number {
    let hash = 2166136261;
    for (let index = 0; index < source.length; index += 1) {
        hash ^= source.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
}

/**
 * Coordinates the palette from seed operation for the CLI UI runtime.
 *
 * @param seed Input value used by the palette from seed operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function paletteFromSeed(seed: number): Omit<CoverVisualModel, 'status' | 'seed' | 'blocks'> {
    const hue = seed % 360;
    const secondaryHue = (hue + 46 + ((seed >>> 8) % 64)) % 360;
    const accentHue = (hue + 172 + ((seed >>> 16) % 38)) % 360;

    return {
        primary: hslToHex(hue, 62, 56),
        secondary: hslToHex(secondaryHue, 56, 42),
        accent: hslToHex(accentHue, 72, 66),
        muted: hslToHex((hue + 24) % 360, 28, 24),
    };
}

/**
 * Coordinates the build block matrix operation for the CLI UI runtime.
 *
 * @param seed Input value used by the build block matrix operation.
 * @param palette Input value used by the build block matrix operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function buildBlockMatrix(
    seed: number,
    palette: Omit<CoverVisualModel, 'status' | 'seed' | 'blocks'>,
): string[][] {
    const colors = [palette.primary, palette.secondary, palette.accent, palette.muted];
    return Array.from({ length: BLOCK_ROWS }, (_, row) => (
        Array.from({ length: BLOCK_COLUMNS }, (_, column) => {
            const wave = Math.sin((row + 1) * 0.9 + (column + seed % 7) * 0.58);
            const grain = seededUnit(seed + row * 97 + column * 53);
            const index = Math.abs(Math.floor((wave + grain * 1.8 + row * 0.28) * colors.length)) % colors.length;
            return colors[index] ?? palette.primary;
        })
    ));
}

/**
 * Coordinates the seeded unit operation for the CLI UI runtime.
 *
 * @param seed Input value used by the seeded unit operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function seededUnit(seed: number): number {
    let value = seed >>> 0;
    value ^= value << 13;
    value ^= value >>> 17;
    value ^= value << 5;
    return (value >>> 0) / 4294967295;
}

/**
 * Coordinates the hsl to hex operation for the CLI UI runtime.
 *
 * @param hue Input value used by the hsl to hex operation.
 * @param saturation Input value used by the hsl to hex operation.
 * @param lightness Input value used by the hsl to hex operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function hslToHex(hue: number, saturation: number, lightness: number): string {
    const normalizedHue = (((hue % 360) + 360) % 360) / 360;
    const normalizedSaturation = clamp01(saturation / 100);
    const normalizedLightness = clamp01(lightness / 100);

    if (normalizedSaturation === 0) {
        const gray = toHexChannel(normalizedLightness);
        return `#${gray}${gray}${gray}`;
    }

    const q = normalizedLightness < 0.5
        ? normalizedLightness * (1 + normalizedSaturation)
        : normalizedLightness + normalizedSaturation - normalizedLightness * normalizedSaturation;
    const p = 2 * normalizedLightness - q;

    return `#${toHexChannel(hueToRgb(p, q, normalizedHue + 1 / 3))}${toHexChannel(hueToRgb(p, q, normalizedHue))}${toHexChannel(hueToRgb(p, q, normalizedHue - 1 / 3))}`;
}

/**
 * Coordinates the hue to rgb operation for the CLI UI runtime.
 *
 * @param p Input value used by the hue to rgb operation.
 * @param q Input value used by the hue to rgb operation.
 * @param t Input value used by the hue to rgb operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function hueToRgb(p: number, q: number, t: number): number {
    let value = t;
    if (value < 0) value += 1;
    if (value > 1) value -= 1;
    if (value < 1 / 6) return p + (q - p) * 6 * value;
    if (value < 1 / 2) return q;
    if (value < 2 / 3) return p + (q - p) * (2 / 3 - value) * 6;
    return p;
}

/**
 * Coordinates the to hex channel operation for the CLI UI runtime.
 *
 * @param value Input value used by the to hex channel operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function toHexChannel(value: number): string {
    return Math.round(clamp01(value) * 255).toString(16).padStart(2, '0');
}

/**
 * Coordinates the clamp01 operation for the CLI UI runtime.
 *
 * @param value Input value used by the clamp01 operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function clamp01(value: number): number {
    return Math.min(1, Math.max(0, value));
}

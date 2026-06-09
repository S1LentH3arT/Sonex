import assert from 'node:assert/strict';

import {
    chooseCoverPatternVariant,
    renderCoverPatternHalfBlocks,
    type CoverPatternPayload,
} from '../src/cover-pattern.js';

/**
 * Defines the palette constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/cover-pattern.test.ts.
 */
const palette = Array.from({ length: 48 }, (_, index) => `#${index.toString(16).padStart(2, '0')}0000`);
/**
 * Defines the grid function.
 *
 * Implements the grid behavior used by src/cli-ui/test/cover-pattern.test.ts.
 *
 * @param size Input value used by the grid operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const grid = (size: number): number[][] => Array.from({ length: size }, (_, row) =>
    Array.from({ length: size }, (_, column) => (row + column) % 48)
);
/**
 * Defines the pattern constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/cover-pattern.test.ts.
 */
const pattern: CoverPatternPayload = {
    source_url: 'https://cdn.example.test/cover.jpg',
    palette,
    variants: {
        32: grid(32),
        48: grid(48),
        64: grid(64),
    },
};

assert.equal(chooseCoverPatternVariant(pattern, { columns: 36, rows: 18 })?.size, 32);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 52, rows: 26 })?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 70, rows: 34 })?.size, 64);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 70, rows: 34 }, { maxSize: 48 })?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 52, rows: 26 }, { maxSize: 48 })?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 10, rows: 4 }), null);

/**
 * Defines the rendered constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/cover-pattern.test.ts.
 */
const rendered = renderCoverPatternHalfBlocks(pattern.variants[32]!, palette);

assert.equal(rendered.length, 16);
assert.equal(rendered[0]?.length, 32);
assert.equal(rendered[0]?.[0]?.char, '▀');
assert.equal(rendered[0]?.[0]?.foreground, palette[0]);
assert.equal(rendered[0]?.[0]?.background, palette[1]);

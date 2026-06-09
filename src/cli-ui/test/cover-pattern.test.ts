import assert from 'node:assert/strict';

import {
    chooseCoverPatternVariant,
    renderCoverPatternHalfBlocks,
    type CoverPatternPayload,
} from '../src/cover-pattern.js';

const palette = Array.from({ length: 48 }, (_, index) => `#${index.toString(16).padStart(2, '0')}0000`);
// Defines the grid function.
const grid = (size: number): number[][] => Array.from({ length: size }, (_, row) =>
    Array.from({ length: size }, (_, column) => (row + column) % 48)
);
const pattern: CoverPatternPayload = {
    source_url: 'https://cdn.example.test/cover.jpg',
    palette,
    variants: {
        32: grid(32),
        48: grid(48),
        64: grid(64),
        80: grid(80),
        96: grid(96),
        72: grid(72),
    },
};

assert.equal(chooseCoverPatternVariant(pattern, { columns: 36, rows: 18 })?.size, 32);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 52, rows: 26 })?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 70, rows: 34 })?.size, 64);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 79, rows: 39 })?.size, 72);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 80, rows: 40 })?.size, 80);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 96, rows: 48 })?.size, 96);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 70, rows: 34 }, { maxSize: 48 })?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 96, rows: 48 }, { maxSize: 80 })?.size, 80);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 10, rows: 4 }), null);

const rendered = renderCoverPatternHalfBlocks(pattern.variants[32]!, palette);

assert.equal(rendered.length, 16);
assert.equal(rendered[0]?.length, 32);
assert.equal(rendered[0]?.[0]?.char, '▀');
assert.equal(rendered[0]?.[0]?.foreground, palette[0]);
assert.equal(rendered[0]?.[0]?.background, palette[1]);

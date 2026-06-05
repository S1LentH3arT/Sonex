import assert from 'node:assert/strict';

import {
    chooseCoverPatternVariant,
    renderCoverPatternHalfBlocks,
    type CoverPatternPayload,
} from '../src/cover-pattern.js';

const palette = Array.from({length: 48}, (_, index) => `#${index.toString(16).padStart(2, '0')}0000`);
const grid = (size: number): number[][] => Array.from({length: size}, (_, row) =>
    Array.from({length: size}, (_, column) => (row + column) % 48)
);
const pattern: CoverPatternPayload = {
    source_url: 'https://cdn.example.test/cover.jpg',
    palette,
    variants: {
        36: grid(36),
        48: grid(48),
        64: grid(64),
    },
};

assert.equal(chooseCoverPatternVariant(pattern, {columns: 36, rows: 18})?.size, 36);
assert.equal(chooseCoverPatternVariant(pattern, {columns: 52, rows: 26})?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, {columns: 70, rows: 34})?.size, 64);
assert.equal(chooseCoverPatternVariant(pattern, {columns: 70, rows: 34}, {maxSize: 48})?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, {columns: 52, rows: 26}, {maxSize: 48})?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, {columns: 10, rows: 4}), null);

const rendered = renderCoverPatternHalfBlocks(pattern.variants[36]!, palette);

assert.equal(rendered.length, 18);
assert.equal(rendered[0]?.length, 36);
assert.equal(rendered[0]?.[0]?.char, '▀');
assert.equal(rendered[0]?.[0]?.foreground, palette[0]);
assert.equal(rendered[0]?.[0]?.background, palette[1]);

import assert from 'node:assert/strict';

import {
    chooseCoverPatternVariant,
    renderCoverPatternHalfBlocks,
    resolveCoverPatternDisplay,
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
        36: grid(36),
        40: grid(40),
        44: grid(44),
        48: grid(48),
        56: grid(56),
        64: grid(64),
        80: grid(80),
        96: grid(96),
        112: grid(112),
        128: grid(128),
        144: grid(144),
        160: grid(160),
        176: grid(176),
        192: grid(192),
        72: grid(72),
    },
};
const unavailablePattern: CoverPatternPayload = {
    source_url: pattern.source_url,
    palette: [],
    variants: {},
    unavailable_reason: 'generation_failed',
};

assert.equal(chooseCoverPatternVariant(pattern, { columns: 35, rows: 17 })?.size, 32);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 36, rows: 18 })?.size, 36);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 40, rows: 20 })?.size, 40);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 44, rows: 22 })?.size, 44);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 52, rows: 26 })?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 56, rows: 28 })?.size, 56);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 70, rows: 34 })?.size, 64);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 79, rows: 39 })?.size, 72);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 80, rows: 40 })?.size, 80);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 96, rows: 48 })?.size, 96);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 111, rows: 56 })?.size, 96);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 112, rows: 55 })?.size, 96);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 112, rows: 56 })?.size, 112);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 128, rows: 64 })?.size, 128);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 144, rows: 72 })?.size, 144);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 160, rows: 80 })?.size, 160);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 176, rows: 88 })?.size, 176);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 191, rows: 96 })?.size, 176);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 192, rows: 95 })?.size, 176);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 192, rows: 96 })?.size, 192);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 70, rows: 34 }, { maxSize: 48 })?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 96, rows: 48 }, { maxSize: 80 })?.size, 80);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 10, rows: 4 }), null);

assert.equal(resolveCoverPatternDisplay(null, { columns: 10, rows: 4 }).status, 'none');
const renderableDisplay = resolveCoverPatternDisplay(pattern, { columns: 40, rows: 20 });
assert.equal(renderableDisplay.status, 'renderable');
assert.equal(renderableDisplay.status === 'renderable' ? renderableDisplay.variant.size : null, 40);
assert.equal(resolveCoverPatternDisplay(pattern, { columns: 10, rows: 4 }).status, 'unfit');
assert.equal(resolveCoverPatternDisplay(pattern, { columns: null, rows: null }).status, 'unfit');
assert.equal(resolveCoverPatternDisplay(unavailablePattern, { columns: 96, rows: 48 }).status, 'unavailable');

const rendered = renderCoverPatternHalfBlocks(pattern.variants[32]!, palette);

assert.equal(rendered.length, 16);
assert.equal(rendered[0]?.length, 32);
assert.equal(rendered[0]?.[0]?.char, '▀');
assert.equal(rendered[0]?.[0]?.foreground, palette[0]);
assert.equal(rendered[0]?.[0]?.background, palette[1]);

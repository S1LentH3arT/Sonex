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
        48: grid(48),
        56: grid(56),
        64: grid(64),
        80: grid(80),
        96: grid(96),
    },
};
const unavailablePattern: CoverPatternPayload = {
    source_url: pattern.source_url,
    palette: [],
    variants: {},
    unavailable_reason: 'generation_failed',
};

assert.equal(chooseCoverPatternVariant(pattern, { columns: 39, rows: 19 }), null);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 40, rows: 20 })?.size, 40);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 44, rows: 22 })?.size, 40);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 52, rows: 26 })?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 56, rows: 28 })?.size, 56);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 70, rows: 34 })?.size, 64);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 79, rows: 39 })?.size, 64);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 80, rows: 40 })?.size, 80);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 96, rows: 48 })?.size, 96);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 111, rows: 56 })?.size, 96);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 112, rows: 55 })?.size, 96);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 192, rows: 96 })?.size, 96);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 70, rows: 34 }, { maxSize: 48 })?.size, 48);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 96, rows: 48 }, { maxSize: 80 })?.size, 80);
const compactDisplay = resolveCoverPatternDisplay(pattern, { columns: 96, rows: 48 }, { maxSize: 80 });
assert.equal(compactDisplay.status === 'renderable' ? compactDisplay.variant.size : null, 80);
assert.equal(chooseCoverPatternVariant(pattern, { columns: 10, rows: 4 }), null);

assert.equal(resolveCoverPatternDisplay(null, { columns: 10, rows: 4 }).status, 'none');
const renderableDisplay = resolveCoverPatternDisplay(pattern, { columns: 40, rows: 20 });
assert.equal(renderableDisplay.status, 'renderable');
assert.equal(renderableDisplay.status === 'renderable' ? renderableDisplay.variant.size : null, 40);
assert.equal(resolveCoverPatternDisplay(pattern, { columns: 10, rows: 4 }).status, 'unfit');
assert.equal(resolveCoverPatternDisplay(pattern, { columns: null, rows: null }).status, 'unfit');
assert.equal(resolveCoverPatternDisplay(unavailablePattern, { columns: 96, rows: 48 }).status, 'unavailable');

const rendered = renderCoverPatternHalfBlocks(pattern.variants[40]!, palette);

assert.equal(rendered.length, 20);
assert.equal(rendered[0]?.length, 40);
assert.equal(rendered[0]?.[0]?.char, '▀');
assert.equal(rendered[0]?.[0]?.foreground, palette[0]);
assert.equal(rendered[0]?.[0]?.background, palette[1]);

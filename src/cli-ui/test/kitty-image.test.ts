import assert from 'node:assert/strict';
import test from 'node:test';

import { decorateKittyImage, kittyDeleteSequence } from '../src/hooks.js';

test('decorates Kitty images with a deletable id', () => {
    const image = decorateKittyImage('\u001B_Gf=100,a=T;data\u001B\\');
    assert.ok(image);
    assert.match(image.sequence, /\u001B_Gi=\d+,f=100,a=T/);
    assert.match(kittyDeleteSequence(image.imageId), new RegExp(`i=${image.imageId}`));
});

test('ignores non-Kitty image output', () => {
    assert.equal(decorateKittyImage('ansi fallback'), null);
});

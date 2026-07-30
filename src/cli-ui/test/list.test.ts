import assert from 'node:assert/strict';
import test from 'node:test';

import { trimList } from '../src/list.js';

test('trimList retains the newest bounded values', () => {
    assert.deepEqual(trimList([1, 2, 3, 4], 2), [3, 4]);
});

test('trimList does not alter a list below its limit', () => {
    assert.deepEqual(trimList(['a', 'b'], 4), ['a', 'b']);
});

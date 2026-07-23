import assert from 'node:assert/strict';

import { hideInputCursor } from '../src/input-cursor.js';

const inverseCursor = `before\u001B[7mX\u001B[27mafter`;
assert.equal(hideInputCursor(inverseCursor), 'beforeXafter');

const coloredCursor = `\u001B[31mred\u001B[39m \u001B[7m \u001B[27m`;
assert.equal(hideInputCursor(coloredCursor), `\u001B[31mred\u001B[39m  `);

assert.equal(hideInputCursor('plain text'), 'plain text');

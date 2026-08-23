import assert from 'node:assert/strict';
import test from 'node:test';
import { SONEX_LOGO, SONEX_LOGO_WIDTH } from '../src/sonex-logo.js';

test('keeps the approved six-row ANSI Shadow wordmark geometry', () => {
    assert.equal(SONEX_LOGO.length, 6);
    assert.equal(SONEX_LOGO_WIDTH, 43);
    assert.deepEqual(SONEX_LOGO.map((line) => Array.from(line).length), [43, 43, 43, 43, 43, 43]);
    assert.equal(SONEX_LOGO[0], '███████╗ ██████╗ ███╗   ██╗███████╗██╗  ██╗');
    assert.equal(SONEX_LOGO[5], '╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝');
});

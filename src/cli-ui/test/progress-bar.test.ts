import assert from 'node:assert/strict';

import {buildProgressBar} from '../src/format.js';

assert.equal(buildProgressBar(0, 10000, 4), "────");
assert.equal(buildProgressBar(5000, 10000, 4), "━━──");
assert.equal(buildProgressBar(9900, 10000, 4), "━━━╸");
assert.equal(buildProgressBar(10000, 10000, 4), "━━━━");
assert.equal(buildProgressBar(5000, 0, 4), "────");

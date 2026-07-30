import assert from 'node:assert/strict';

import { formatMiniTrackSubtitle } from '../src/format.js';

assert.equal(formatMiniTrackSubtitle('Artist', 'Album'), 'Artist-Album');
assert.equal(formatMiniTrackSubtitle('Artist', '-'), 'Artist');
assert.equal(formatMiniTrackSubtitle('-', 'Album'), 'Album');
assert.equal(formatMiniTrackSubtitle('-', '-'), '');
assert.equal(formatMiniTrackSubtitle('', ''), '');

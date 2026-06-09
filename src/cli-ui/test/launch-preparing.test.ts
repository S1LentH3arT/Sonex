import assert from 'node:assert/strict';

import {
    LAUNCH_PREPARING_INTERVAL_MS,
    launchPreparingText,
    shouldStartLaunchPreparing,
} from '../src/launch-preparing.js';

assert.equal(LAUNCH_PREPARING_INTERVAL_MS, 1000);
assert.equal(launchPreparingText(0), 'Launch preparing.');
assert.equal(launchPreparingText(1), 'Launch preparing..');
assert.equal(launchPreparingText(2), 'Launch preparing...');
assert.equal(launchPreparingText(3), 'Launch preparing.');

assert.equal(shouldStartLaunchPreparing({ kind: 'tool', title: 'Searching YouTube', status: 'pending' }), true);
assert.equal(shouldStartLaunchPreparing({ kind: 'tool', title: 'Caching YouTube audio', status: 'pending' }), true);
assert.equal(shouldStartLaunchPreparing({ kind: 'tool', title: 'Searching Spotify', status: 'pending' }), true);
assert.equal(shouldStartLaunchPreparing({ kind: 'tool', title: 'Searching online audio', status: 'pending' }), true);
assert.equal(shouldStartLaunchPreparing({ kind: 'tool', title: 'Caching online audio', status: 'pending' }), true);
assert.equal(shouldStartLaunchPreparing({ kind: 'tool', title: 'Finished play_youtube_song', status: 'success' }), false);
assert.equal(shouldStartLaunchPreparing({ kind: 'status', title: 'Searching YouTube', status: 'pending' }), false);

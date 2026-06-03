import assert from 'node:assert/strict';

import {
    FULL_LAYOUT_MIN_COLUMNS,
    FULL_LAYOUT_MIN_ROWS,
    resolveMiniPlayerChrome,
    resolveShellLayout,
} from '../src/layout.js';

assert.equal(FULL_LAYOUT_MIN_COLUMNS, 114);
assert.equal(FULL_LAYOUT_MIN_ROWS, 24);

assert.equal(
    resolveShellLayout({
        columns: 120,
        rows: 30,
        isPlaying: true,
        preferredLayout: 'full',
        smallPlaybackFocus: 'player',
    }),
    'full',
);

assert.equal(
    resolveShellLayout({
        columns: 90,
        rows: 30,
        isPlaying: true,
        preferredLayout: 'full',
        smallPlaybackFocus: 'player',
    }),
    'miniPlayer',
);

assert.equal(
    resolveShellLayout({
        columns: 120,
        rows: 18,
        isPlaying: true,
        preferredLayout: 'full',
        smallPlaybackFocus: 'player',
    }),
    'miniPlayer',
);

assert.equal(
    resolveShellLayout({
        columns: 80,
        rows: 20,
        isPlaying: false,
        preferredLayout: 'full',
        smallPlaybackFocus: 'player',
    }),
    'chat',
);

assert.equal(
    resolveShellLayout({
        columns: 80,
        rows: 20,
        isPlaying: true,
        preferredLayout: 'full',
        smallPlaybackFocus: 'chat',
    }),
    'chat',
);

assert.equal(
    resolveShellLayout({
        columns: null,
        rows: null,
        isPlaying: true,
        preferredLayout: 'full',
        smallPlaybackFocus: 'player',
    }),
    'miniPlayer',
);

assert.deepEqual(
    resolveMiniPlayerChrome({layout: 'miniPlayer', smallPlaybackFocus: 'player'}),
    {
        inputOnly: true,
        showConversation: false,
        showStatus: false,
        switchHint: 'Tab to switch to chat',
    },
);

assert.equal(
    resolveMiniPlayerChrome({layout: 'chat', smallPlaybackFocus: 'chat'}).switchHint,
    'Tab to switch to player',
);

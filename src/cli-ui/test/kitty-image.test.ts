import assert from 'node:assert/strict';
import test from 'node:test';

import { kittyDeleteSequence, kittyImageSequence } from '../src/hooks.js';

test('encodes bounded PNG data directly as a Kitty image', () => {
    const previousTerm = process.env.TERM;
    process.env.TERM = 'xterm-kitty';
    try {
        const image = kittyImageSequence({ type: 'cover_image', source_url: 'cover-a', format: 'png', width: 100, height: 100, data: 'a'.repeat(5000) }, 32, 16);
        assert.match(image.art ?? '', /\u001B_Gi=\d+,f=100,a=T,c=32,r=16,q=2,m=1;/);
        assert.match(image.art ?? '', /m=0;/);
        assert.ok(image.imageId);
        assert.match(kittyDeleteSequence(image.imageId ?? 0), /a=d,d=I/);
    } finally {
        if (previousTerm === undefined) delete process.env.TERM;
        else process.env.TERM = previousTerm;
    }
});

test('falls back under tmux even when Kitty exports its window id', () => {
    const previousTerm = process.env.TERM;
    const previousKittyId = process.env.KITTY_WINDOW_ID;
    const previousTmux = process.env.TMUX;
    process.env.TERM = 'xterm-kitty';
    process.env.KITTY_WINDOW_ID = '1';
    process.env.TMUX = '/tmp/tmux';
    try {
        const image = kittyImageSequence({ type: 'cover_image', source_url: 'cover-a', format: 'png', width: 100, height: 100, data: 'encoded' }, 32, 16);
        assert.equal(image.art, null);
        assert.equal(image.imageId, null);
    } finally {
        if (previousTerm === undefined) delete process.env.TERM;
        else process.env.TERM = previousTerm;
        if (previousKittyId === undefined) delete process.env.KITTY_WINDOW_ID;
        else process.env.KITTY_WINDOW_ID = previousKittyId;
        if (previousTmux === undefined) delete process.env.TMUX;
        else process.env.TMUX = previousTmux;
    }
});

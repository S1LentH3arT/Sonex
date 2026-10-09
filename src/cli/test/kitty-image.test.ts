import assert from 'node:assert/strict';
import test from 'node:test';
import { TerminalCover, coverSize, supportsKittyGraphics } from '../src/terminal-cover.js';
import type { CoverImageEvent } from '../src/types.js';

const image: CoverImageEvent = {
    type: 'cover_image', source_url: 'cover-a', format: 'png',
    width: 100, height: 100, data: 'a'.repeat(5000),
};

test('uploads once, replaces placements on resize, and deletes on release', () => {
    const writes: string[] = [];
    const cover = new TerminalCover(true, value => writes.push(value));
    const id = cover.retain(image)!;
    const first = cover.transform(`before${cover.marker(id, 32, 16)}after`);
    assert.match(first, /a=t,f=100/);
    assert.match(first, /m=1;/);
    assert.match(first, /m=0;/);
    assert.match(first, /a=p,.*c=32,r=16,C=1/);
    assert.ok(first.startsWith('before'));
    assert.ok(first.endsWith('after'));

    const resized = cover.transform(cover.marker(id, 20, 10));
    assert.doesNotMatch(resized, /a=t/);
    assert.match(resized, /a=d,d=i/);
    assert.match(resized, /c=20,r=10,C=1/);
    cover.reset();
    assert.match(writes.at(-1)!, /a=d,d=i/);
    assert.doesNotMatch(cover.transform(cover.marker(id, 20, 10)), /a=t/);
    cover.release(id);
    assert.match(writes.at(-1)!, /a=d,d=I/);
    assert.equal(cover.transform(cover.marker(id, 20, 10)), '');
});

test('clear, track switch and exit remove only owned images', () => {
    const writes: string[] = [];
    const cover = new TerminalCover(true, value => writes.push(value));
    const first = cover.retain(image)!;
    cover.transform(cover.marker(first, 32, 16));
    const cleared = cover.transform('\u001b[2J' + cover.marker(first, 32, 16));
    assert.ok(cleared.indexOf('a=d,d=i') < cleared.indexOf('\u001b[2J'));
    assert.doesNotMatch(cleared, /a=t/);
    const second = cover.retain({ ...image, source_url: 'cover-b' })!;
    cover.release(first);
    assert.match(writes.at(-1)!, new RegExp(`d=I,i=${first},`));
    cover.transform(cover.marker(second, 32, 16));
    cover.dispose();
    assert.match(writes.at(-1)!, new RegExp(`d=I,i=${second},`));
    assert.equal(cover.transform(cover.marker(second, 32, 16)), '');
});

test('fallback and invalid images never emit graphics or private markers', () => {
    assert.equal(supportsKittyGraphics({ TERM: 'xterm-kitty' }), true);
    assert.equal(supportsKittyGraphics({ KITTY_WINDOW_ID: '1', TMUX: '/tmp/tmux' }), false);
    assert.equal(supportsKittyGraphics({ TERM: 'xterm-kitty', STY: 'screen' }), false);
    assert.equal(supportsKittyGraphics({ TERM: 'xterm-256color' }), false);
    const cover = new TerminalCover(false, () => assert.fail('unexpected write'));
    assert.equal(cover.retain(image), null);
    assert.equal(cover.transform(`plain${cover.marker(1, 32, 16)}`), 'plain');
    const enabled = new TerminalCover(true, () => assert.fail('unexpected write'));
    for (const invalid of [
        { ...image, width: 0 }, { ...image, height: Infinity },
        { ...image, data: '\u001b[2J' }, { ...image, data: 'a'.repeat(3_000_000) },
    ]) assert.equal(enabled.retain(invalid), null);
    assert.deepEqual(coverSize(image, 32, 16), { columns: 32, rows: 16 });
    assert.deepEqual(coverSize({ ...image, width: 200 }, 32, 16), { columns: 32, rows: 8 });
    assert.deepEqual(coverSize({ ...image, height: 200 }, 32, 16), { columns: 16, rows: 16 });
});

test('actual Ink output reserves cover rows, consumes anchors and reuses uploads', async () => {
    const [{ default: React }, { Box, Text, render }, { PassThrough }, { useCoverArt }, { createIncrementalStdout }] = await Promise.all([
        import('react'), import('ink'), import('node:stream'),
        import('../src/cover-image.js'), import('../src/terminal-frame-writer.js'),
    ]);
    const previousTerm = process.env.TERM;
    const previousTmux = process.env.TMUX;
    const previousSty = process.env.STY;
    process.env.TERM = 'xterm-kitty';
    delete process.env.TMUX;
    delete process.env.STY;
    const stream = Object.assign(new PassThrough(), { columns: 80, rows: 24, isTTY: true });
    let output = '';
    stream.on('data', chunk => { output += chunk.toString(); });
    const stdout = createIncrementalStdout(stream as unknown as NodeJS.WriteStream);
    const stdin = new PassThrough();
    const Fixture = ({ width }: { width: number }) => {
        const art = useCoverArt(image, width, width / 2);
        return React.createElement(Box, { flexDirection: 'column' },
            React.createElement(Text, null, 'ABOVE'), art,
            React.createElement(Text, null, 'BELOW'));
    };
    const app = render(React.createElement(Fixture, { width: 8 }), {
        stdout, stdin, debug: true, patchConsole: false, exitOnCtrlC: false,
    });
    try {
        await new Promise(resolve => setImmediate(resolve));
        assert.match(output, /a=t,f=100/);
        assert.match(output, /c=8,r=4,C=1/);
        assert.doesNotMatch(output, /sonex-cover=/);
        const first = output.slice(output.lastIndexOf('ABOVE'));
        assert.equal(first.slice(0, first.indexOf('BELOW')).split('\n').length - 1, 5);
        output = '';
        app.rerender(React.createElement(Fixture, { width: 12 }));
        await new Promise(resolve => setImmediate(resolve));
        assert.match(output, /c=12,r=6,C=1/);
        assert.doesNotMatch(output, /a=t/);
        app.unmount();
        await new Promise(resolve => setImmediate(resolve));
        assert.match(output, /a=d,d=I/);
    } finally {
        app.unmount();
        stdout.dispose();
        stdin.destroy();
        stream.destroy();
        for (const [key, value] of Object.entries({ TERM: previousTerm, TMUX: previousTmux, STY: previousSty })) {
            if (value === undefined) delete process.env[key];
            else process.env[key] = value;
        }
    }
});

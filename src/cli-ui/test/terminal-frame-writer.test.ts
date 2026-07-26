import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
    APP_CLEAR_SCREEN,
    createIncrementalStdout,
    INK_CLEAR_SCREEN,
    IncrementalTerminalFrameWriter,
} from '../src/terminal-frame-writer.js';

test('keeps the first full-screen frame intact', () => {
    const writer = new IncrementalTerminalFrameWriter(() => ({ columns: 80, rows: 24 }));
    const frame = `${INK_CLEAR_SCREEN}first\nsecond\nthird`;

    assert.equal(writer.transform(frame), frame);
});

test('updates only changed rows after the first full-screen frame', () => {
    const writer = new IncrementalTerminalFrameWriter(() => ({ columns: 80, rows: 24 }));
    writer.transform(`${INK_CLEAR_SCREEN}first\ncursor on\nthird`);

    const update = writer.transform(`${INK_CLEAR_SCREEN}first\ncursor off\nthird`);

    assert.equal(update, '\u001B7\u001B[2;1H\u001B[2Kcursor off\u001B8');
    assert.equal(update?.includes(INK_CLEAR_SCREEN), false);
    assert.equal(update?.includes('first'), false);
    assert.equal(update?.includes('third'), false);
});

test('suppresses identical full-screen frames', () => {
    const writer = new IncrementalTerminalFrameWriter(() => ({ columns: 80, rows: 24 }));
    const frame = `${INK_CLEAR_SCREEN}first\nsecond`;
    writer.transform(frame);

    assert.equal(writer.transform(frame), null);
});

test('forwards explicit clears and resets the cached frame', () => {
    const writer = new IncrementalTerminalFrameWriter(() => ({ columns: 80, rows: 24 }));
    writer.transform(`${INK_CLEAR_SCREEN}first\nsecond`);

    assert.equal(writer.transform(APP_CLEAR_SCREEN), APP_CLEAR_SCREEN);

    const nextFrame = `${INK_CLEAR_SCREEN}first\nchanged`;
    assert.equal(writer.transform(nextFrame), nextFrame);
});

test('uses a full redraw after terminal dimensions change', () => {
    let dimensions = { columns: 80, rows: 24 };
    const writer = new IncrementalTerminalFrameWriter(() => dimensions);
    writer.transform(`${INK_CLEAR_SCREEN}first\nsecond`);
    dimensions = { columns: 100, rows: 30 };

    const resizedFrame = `${INK_CLEAR_SCREEN}first\nchanged`;
    assert.equal(writer.transform(resizedFrame), resizedFrame);
});

test('createIncrementalStdout exposes a cache reset handle', () => {
    const writes: string[] = [];
    const stdout = {
        columns: 80,
        rows: 24,
        isTTY: true,
        write: (chunk: string) => {
            writes.push(chunk);
            return true;
        },
    } as unknown as NodeJS.WriteStream;
    const incremental = createIncrementalStdout(stdout);
    assert.equal(incremental.rows, undefined);
    assert.equal(stdout.rows, 24);

    incremental.write(`${INK_CLEAR_SCREEN}first`);
    incremental.write(`${INK_CLEAR_SCREEN}second`);
    incremental.reset();
    incremental.write(`${INK_CLEAR_SCREEN}third`);

    assert.equal(writes.at(-1), `${INK_CLEAR_SCREEN}third`);
});

test('non-TTY stdout strips terminal controls without replaying plain text', () => {
    const writes: string[] = [];
    const stdout = {
        columns: 80,
        rows: 24,
        isTTY: false,
        write: (chunk: string) => {
            writes.push(chunk);
            return true;
        },
    } as unknown as NodeJS.WriteStream;
    const incremental = createIncrementalStdout(stdout);

    incremental.write('\u001B[2K\u001B[1A\u001B[G\u001B[31mplain\u001B[0m');

    assert.deepEqual(writes, ['plain']);
});

test('CLI entrypoint gives Ink the incremental stdout adapter', () => {
    const source = readFileSync(new URL('../src/index.tsx', import.meta.url), 'utf8');

    assert.match(
        source,
        /const incrementalStdout = createIncrementalStdout\(process\.stdout\)/,
    );
    assert.match(
        source,
        /terminalSurface\.prepare\(\)[\s\S]*<App terminalSurface=\{terminalSurface\} terminalStdout=\{process\.stdout\} \/>[\s\S]*stdin: process\.stdin,[\s\S]*stdout: incrementalStdout/,
    );
    assert.match(source, /resetFrame: incrementalStdout\.reset/);
    assert.doesNotMatch(source, /createMouseInputAdapter|mouseInput/);
});

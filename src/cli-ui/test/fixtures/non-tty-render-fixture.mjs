import React from 'react';
import { Static, Text, render } from 'ink';

import { createIncrementalStdout } from '../../dist/terminal-frame-writer.js';
import { TerminalSurfaceController } from '../../dist/terminal-surface.js';

const incremental = createIncrementalStdout(process.stdout);
const surface = new TerminalSurfaceController({
    isTTY: false,
    write: (value) => process.stdout.write(value),
    resetFrame: incremental.reset,
});

surface.prepare();
const record = { id: 1, content: 'NON_TTY_RECORD' };
const frame = (tail) => React.createElement(
    React.Fragment,
    null,
    React.createElement(
        Static,
        { items: [record] },
        (item) => React.createElement(Text, { key: item.id }, item.content),
    ),
    React.createElement(Text, null, tail),
);
const app = render(frame('NON_TTY_FIRST'), {
    exitOnCtrlC: false,
    stdin: process.stdin,
    stdout: incremental,
});
surface.attachRendererClear(() => app.clear());
const exit = app.waitUntilExit();
app.rerender(frame('NON_TTY_SECOND'));
app.rerender(frame('NON_TTY_THIRD'));
app.unmount();
await exit.finally(() => surface.dispose());

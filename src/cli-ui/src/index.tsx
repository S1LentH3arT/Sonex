import React from 'react';
import { render } from 'ink';

import { App } from './App.js';
import { createIncrementalStdout } from './terminal-frame-writer.js';
import { TerminalSurfaceController } from './terminal-surface.js';

const incrementalStdout = createIncrementalStdout(process.stdout);
const terminalSurface = new TerminalSurfaceController({
    isTTY: process.stdout.isTTY === true,
    write: (value) => {
        process.stdout.write(value);
    },
    resetFrame: incrementalStdout.reset,
});

terminalSurface.prepare();

let app: ReturnType<typeof render>;
try {
    app = render(
        <App terminalSurface={terminalSurface} terminalStdout={process.stdout} />,
        {
            exitOnCtrlC: false,
            stdin: process.stdin,
            stdout: incrementalStdout,
        },
    );
} catch (error) {
    terminalSurface.dispose();
    throw error;
}

terminalSurface.attachRendererClear(() => app.clear());

const cleanup = (): void => terminalSurface.dispose();
const stopFromSignal = (exitCode: number): void => {
    process.exitCode = exitCode;
    try {
        app.unmount();
    } finally {
        cleanup();
    }
};
const onSigint = (): void => stopFromSignal(130);
const onSigterm = (): void => stopFromSignal(143);

process.once('SIGINT', onSigint);
process.once('SIGTERM', onSigterm);

void app.waitUntilExit().finally(() => {
    process.removeListener('SIGINT', onSigint);
    process.removeListener('SIGTERM', onSigterm);
    cleanup();
});

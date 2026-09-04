import React, { useEffect, useReducer } from 'react';
import { Box, Static, Text, render } from 'ink';

import { createIncrementalStdout } from '../../dist/terminal-frame-writer.js';
import { TerminalSurfaceController } from '../../dist/terminal-surface.js';
import {
    createTranscriptState,
    transcriptReducer,
} from '../../dist/transcript.js';

const incremental = createIncrementalStdout(process.stdout);
const surface = new TerminalSurfaceController({
    isTTY: process.stdout.isTTY === true,
    write: (value) => process.stdout.write(value),
    resetFrame: incremental.reset,
});

let ink;
const signalMode = process.env.SONEX_APPEND_FIXTURE_SIGNAL === '1';
const presentation = {
    contentWidth: 76,
    headerVariant: 'mascot',
    language: 'en',
};

const Fixture = () => {
    const [transcript, dispatchTranscript] = useReducer(
        transcriptReducer,
        undefined,
        createTranscriptState,
    );

    useEffect(() => {
        dispatchTranscript({
            type: 'commit',
            items: [
                { type: 'message', role: 'agent', content: 'RECORD_BEFORE_ALT' },
                ...Array.from({ length: 40 }, (_, index) => ({
                    type: 'message',
                    role: 'agent',
                    content: `STATIC_HISTORY_${index}`,
                })),
            ],
            presentation,
        });

        const enter = setTimeout(() => {
            surface.transition('alternate', () => {
                dispatchTranscript({ type: 'setSurface', surface: 'alternate' });
            });
            dispatchTranscript({
                type: 'commit',
                items: [{ type: 'message', role: 'agent', content: 'RECORD_DURING_ALT' }],
                presentation,
            });
        }, 20);

        const leave = signalMode ? null : setTimeout(() => {
            surface.transition('main', () => {
                dispatchTranscript({ type: 'setSurface', surface: 'main' });
            });
        }, 50);

        const finish = signalMode ? null : setTimeout(() => {
            ink.unmount();
        }, 100);

        return () => {
            clearTimeout(enter);
            if (leave) clearTimeout(leave);
            if (finish) clearTimeout(finish);
        };
    }, []);

    return React.createElement(
        React.Fragment,
        null,
        React.createElement(
            Static,
            { items: transcript.records },
            (record) => React.createElement(
                Text,
                { key: record.sequence },
                record.item.type === 'message' ? record.item.content : 'INFO_BANNER',
            ),
        ),
        React.createElement(
            Box,
            {
                height: transcript.surface === 'alternate' ? process.stdout.rows - 1 : undefined,
                flexDirection: 'column',
            },
            transcript.surface === 'alternate'
                ? React.createElement(Text, null, 'ALT_SURFACE')
                : [
                    React.createElement(Text, { key: 'tail' }, 'LIVE_TAIL'),
                    ...Array.from({ length: 30 }, (_, index) => React.createElement(
                        Text,
                        { key: `main-${index}` },
                        `TALL_MAIN_LINE_${index}`,
                    )),
                ],
        ),
    );
};

surface.prepare();
ink = render(React.createElement(Fixture), {
    exitOnCtrlC: false,
    stdin: process.stdin,
    stdout: incremental,
});
surface.attachRendererClear(() => ink.clear());

const stopFromSignal = () => {
    process.exitCode = 143;
    try {
        ink.unmount();
    } finally {
        surface.dispose();
    }
};

process.once('SIGTERM', stopFromSignal);
await ink.waitUntilExit().finally(() => {
    process.removeListener('SIGTERM', stopFromSignal);
    surface.dispose();
});

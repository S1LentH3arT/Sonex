import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';

const stripAnsi = (value: string): string => value.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');

test('renders tool names in bold navy and values in white ANSI spans', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { CommittedRecord }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const stdout = new PassThrough() as PassThrough & {
        columns: number;
        rows: number;
        isTTY: boolean;
    };
    stdout.columns = 80;
    stdout.rows = 24;
    stdout.isTTY = true;
    let output = '';
    stdout.on('data', (chunk) => {
        output += chunk.toString();
    });

    const stdin = new PassThrough();
    const app = render(
        React.createElement(CommittedRecord, {
            record: {
                sequence: 1,
                item: {
                    type: 'message',
                    role: 'agent',
                    content: 'Bash npm test',
                    segments: [
                        { text: 'Bash', style: 'tool_name' },
                        { text: ' npm test', style: 'tool_value' },
                    ],
                },
                presentation: {
                    contentWidth: 60,
                    headerVariant: 'complete',
                    language: 'en',
                },
            },
        }),
        {
            stdout,
            stdin,
            debug: true,
            exitOnCtrlC: false,
        },
    );

    await new Promise((resolve) => setImmediate(resolve));
    app.unmount();
    stdin.destroy();
    stdout.destroy();

    const navyAnsi = String.raw`\u001b\[(?:38;2;24;46;102|38;5;24)m`;
    const blueAnsi = String.raw`\u001b\[(?:38;2;59;130;246|38;5;75)m`;
    const whiteAnsi = String.raw`\u001b\[(?:38;2;255;255;255|38;5;231)m`;
    assert.match(
        output,
        new RegExp(String.raw`\u001b\[1m${blueAnsi}•\u001b\[22m`),
    );
    assert.match(output, new RegExp(navyAnsi));
    assert.match(
        output,
        new RegExp(String.raw`\u001b\[1m${navyAnsi}Bash\u001b\[22m`),
    );
    assert.match(output, new RegExp(`${whiteAnsi} npm test`));
    assert.match(stripAnsi(output), /• Bash npm test/);
    assert.doesNotMatch(stripAnsi(output), /Agent|[└│]/);
});

test('renders message dividers, aligned continuations, and complete warning colors', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { CommittedTranscript }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const stdout = new PassThrough() as PassThrough & {
        columns: number;
        rows: number;
        isTTY: boolean;
    };
    stdout.columns = 20;
    stdout.rows = 24;
    stdout.isTTY = true;
    let output = '';
    stdout.on('data', (chunk) => {
        output += chunk.toString();
    });

    const presentation = {
        contentWidth: 16,
        headerVariant: 'compact' as const,
        language: 'en' as const,
    };
    const stdin = new PassThrough();
    const app = render(
        React.createElement(CommittedTranscript, {
            records: [
                {
                    sequence: 1,
                    item: { type: 'message', role: 'user', content: 'hello\nwrapped' },
                    presentation,
                },
                {
                    sequence: 2,
                    item: {
                        type: 'message',
                        role: 'agent',
                        content: 'Bash danger',
                        tone: 'warning',
                        segments: [
                            { text: 'Bash', style: 'tool_name' },
                            { text: ' danger', style: 'tool_value' },
                        ],
                    },
                    presentation,
                },
                {
                    sequence: 3,
                    item: { type: 'message', role: 'agent', content: 'caution', tone: 'error' },
                    presentation,
                },
                {
                    sequence: 4,
                    item: { type: 'message', role: 'agent', content: 'system', tone: 'system', theme: 'muted' },
                    presentation,
                },
            ],
        }),
        {
            stdout,
            stdin,
            debug: true,
            exitOnCtrlC: false,
        },
    );

    await new Promise((resolve) => setImmediate(resolve));
    app.unmount();
    stdin.destroy();
    stdout.destroy();

    const plain = stripAnsi(output);
    assert.match(
        plain,
        / • hello\n   wrapped\n\n ─{18}\n\n • Bash danger\n\n ─{18}\n\n • caution\n\n ─{18}\n\n • system\n\n ─{18}/,
    );
    assert.doesNotMatch(plain, /User|Agent|System|Warning|Caution|[└│]/);

    const grayAnsi = String.raw`\u001b\[(?:38;2;128;135;145|38;5;145)m`;
    const whiteAnsi = String.raw`\u001b\[(?:38;2;255;255;255|38;5;231)m`;
    const yellowAnsi = String.raw`\u001b\[(?:38;2;212;167;44|38;5;179)m`;
    const redAnsi = String.raw`\u001b\[(?:38;2;239;68;68|38;5;203)m`;
    const purpleAnsi = String.raw`\u001b\[(?:38;2;200;166;255|38;5;183)m`;
    assert.match(output, new RegExp(`${grayAnsi}─{18}`));
    assert.match(output, new RegExp(String.raw`\u001b\[1m${grayAnsi}•\u001b\[22m${whiteAnsi} hello`));
    assert.match(output, new RegExp(String.raw`\u001b\[1m${yellowAnsi}•\u001b\[22m Bash danger`));
    assert.match(output, new RegExp(String.raw`\u001b\[1m${redAnsi}•\u001b\[22m caution`));
    assert.match(output, new RegExp(String.raw`\u001b\[1m${purpleAnsi}•\u001b\[22m${whiteAnsi} system`));
});

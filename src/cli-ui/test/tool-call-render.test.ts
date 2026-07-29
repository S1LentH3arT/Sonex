import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';

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
                    content: 'Bash  npm test',
                    segments: [
                        { text: 'Bash', style: 'tool_name' },
                        { text: '  npm test', style: 'tool_value' },
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

    const navyAnsi = String.raw`\u001b\[(?:38;2;47;93;140|38;5;67)m`;
    const whiteAnsi = String.raw`\u001b\[(?:38;2;255;255;255|38;5;231)m`;
    assert.match(output, new RegExp(navyAnsi));
    assert.match(
        output,
        new RegExp(String.raw`\u001b\[1m${navyAnsi}Bash\u001b\[22m`),
    );
    assert.match(output, new RegExp(`${whiteAnsi}  npm test`));
});

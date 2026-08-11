import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';

const stripAnsi = (value: string): string => value.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');

test('renders a partial streamed answer without its completion divider', async () => {
    const [{ default: React }, { render }, { ChatBubble }] = await Promise.all([
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
        React.createElement(ChatBubble, {
            role: 'agent',
            content: 'Partial answer',
            contentWidth: 60,
            showDivider: false,
        }),
        { stdout, stdin, debug: true, exitOnCtrlC: false },
    );

    await new Promise((resolve) => setImmediate(resolve));
    app.unmount();
    stdin.destroy();
    stdout.destroy();

    const plain = stripAnsi(output);
    assert.match(plain, /• Partial answer/);
    assert.doesNotMatch(plain, /─/);
});

import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';

test('renders the Agent Working row with the exact interrupt hint styling', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { AgentWorkingStatus }] = await Promise.all([
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
    const app = render(React.createElement(AgentWorkingStatus), {
        stdout,
        stdin,
        debug: true,
        exitOnCtrlC: false,
    });

    await new Promise((resolve) => setImmediate(resolve));
    app.unmount();
    stdin.destroy();
    stdout.destroy();

    const purpleAnsi = String.raw`\u001b\[(?:38;2;200;166;255|38;5;183)m`;
    assert.match(
        output,
        new RegExp(`${purpleAnsi}⠋ ${String.raw`\u001b\[3m`}Working${String.raw`\u001b\[23m`}`),
    );
    const grayAnsi = String.raw`\u001b\[(?:38;2;128;135;145|38;5;145)m`;
    assert.match(
        output,
        new RegExp(String.raw`\u001b\[1m${grayAnsi} • Esc to interrupt`),
    );
});

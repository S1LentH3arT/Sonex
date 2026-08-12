import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';

import type { ConfirmState } from '../src/types.js';

const stripAnsi = (value: string): string => value.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');

test('renders semantic connection rows, fixed provider width, and retry blinking', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { CompactConfirm }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const stdout = new PassThrough() as PassThrough & { columns: number; rows: number; isTTY: boolean };
    stdout.columns = 80;
    stdout.rows = 24;
    stdout.isTTY = true;
    const stdin = new PassThrough() as PassThrough & { isTTY: boolean; setRawMode: (enabled: boolean) => void };
    stdin.isTTY = true;
    stdin.setRawMode = () => undefined;
    let output = '';
    stdout.on('data', (chunk) => { output += chunk.toString(); });
    const confirm: NonNullable<ConfirmState> = {
        id: 'music-connections',
        tool_name: 'music_connection',
        tool_args: { hint: '↑/↓ to select · Enter to connect/check · Esc to close' },
        message: 'Music connections',
        choices: [
            { value: 'spotify', label: 'Spotify', description: 'Connected · SILENCE', connection_status: 'connected' },
            { value: 'audius', label: 'Audius', description: 'Not connected', connection_status: 'missing' },
            { value: 'netease', label: 'NetEase Cloud Music', description: 'press Enter to retry', connection_status: 'warning' },
            { value: 'jamendo', label: 'Jamendo', description: 'Checking connection...', connection_status: 'checking' },
            { value: 'long-account', label: 'Long Account', description: `Connected · ${'界'.repeat(40)}`, connection_status: 'connected' },
        ],
    };
    const app = render(React.createElement(CompactConfirm, {
        confirm,
        confirmIndex: 2,
        input: '',
        setInput: () => undefined,
        onSubmit: () => undefined,
        inputFocus: false,
        inputRevision: 0,
        panelWidth: 74,
    }), { stdout, stdin, debug: true, exitOnCtrlC: false });

    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setTimeout(resolve, 550));
    const plain = stripAnsi(output);
    try {
        assert.match(plain, /• Spotify {17}Connected · SILENCE/);
        assert.match(plain, /• Audius {18}Not connected/);
        assert.match(plain, /• NetEase Cloud Music {5}press Enter to retry/);
        assert.match(plain, /◦ Jamendo {17}Checking connection\.\.\./);
        assert.match(plain, /• Jamendo {17}Checking connection\.\.\./);
        assert.match(plain, /• Long Account {12}Connected · 界+…/);
        assert.match(plain, /↑\/↓ to select · Enter to connect\/check · Esc to close/);
        assert.match(output, /\u001b\[(?:38;2;29;185;84|38;5;78)m(?:•|Connected)/);
        assert.match(output, /\u001b\[(?:38;2;239;68;68|38;5;203)m(?:•|Not connected)/);
        assert.match(
            output,
            /\u001b\[1m\u001b\[(?:38;2;250;204;21|38;5;220)m• [^\n]*\u001b\[(?:38;2;250;204;21|38;5;220)mpress Enter to retry/,
        );
    } finally {
        app.unmount();
        stdin.destroy();
        stdout.destroy();
    }
});

import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';

import type { ExtensionPanelState } from '../src/types.js';

const stripAnsi = (value: string): string => value.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');

test('renders extension descriptions and detail lifecycle fields', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { ExtensionPanelOverlay }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/extension-panel.js'),
    ]);
    const stdout = new PassThrough() as PassThrough & { columns: number; rows: number; isTTY: boolean };
    stdout.columns = 100;
    stdout.rows = 24;
    stdout.isTTY = true;
    const stdin = new PassThrough() as PassThrough & { isTTY: boolean; setRawMode: (enabled: boolean) => void };
    stdin.isTTY = true;
    stdin.setRawMode = () => undefined;
    let output = '';
    stdout.on('data', (chunk) => { output += chunk.toString(); });
    const panel: NonNullable<ExtensionPanelState> = {
        view: 'detail',
        title: '',
        hint: '↑/↓ select · Enter act · Esc back',
        selectedExtension: 'spotify',
        extensions: [
            {
                id: 'spotify',
                name: 'Spotify',
                description: 'search Spotify and play on connected devices',
                status: 'enabled',
                enabled: true,
                configured: true,
                tags: ['Search', 'Stream'],
                reset_available: true,
                setup_available: true,
                signal: 'green',
            },
        ],
        detail: {
            status: 'enabled',
            action: 'disable',
            reset_available: true,
        },
    };
    const app = render(React.createElement(ExtensionPanelOverlay, {
        panel,
        selectedIndex: 0,
        width: 94,
    }), { stdout, stdin, debug: true, exitOnCtrlC: false });

    await new Promise((resolve) => setImmediate(resolve));
    const plain = stripAnsi(output);
    try {
        assert.match(plain, /• Spotify/);
        assert.match(plain, /Status       Enabled/);
        assert.match(plain, /Tag          Search · Stream/);
        assert.match(plain, /Quick Check/);
        assert.match(plain, /Disable/);
        assert.match(plain, /Reset/);
    } finally {
        app.unmount();
        stdin.destroy();
        stdout.destroy();
    }
});

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PassThrough } from 'node:stream';
import test from 'node:test';
import stringWidth from 'string-width';

import { dependencyLine } from '../src/extension-panel.js';
import type { ExtensionPanelState } from '../src/types.js';

const stripAnsi = (value: string): string => value.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');
const extensionSource = readFileSync(new URL('../src/extension-panel.tsx', import.meta.url), 'utf8');

test('uses the shared blue selected state for Quick Check and Reset', () => {
    assert.match(extensionSource, /if \(action === "reset" \|\| action === "prepare_reset"\) return PANEL_PRIMARY/);
    assert.doesNotMatch(extensionSource, /selectedColor: action === "prepare_reset"/);
    assert.match(extensionSource, /preserveColorWhenSelected: !\["disable", "setup", "quick_check", "prepare_reset"\]\.includes\(action\)/);
    assert.doesNotMatch(extensionSource, /const extensionActionBold = [^;]+prepare_reset/);
});

test('renders extension status with the signal color in bold', () => {
    assert.match(extensionSource, /text: `Status       \$\{statusLabel\(detail\.status\)\}`, color: extensionStatusColor, bold: true/);
});

test('aligns dependency names after every status marker and animates unknown progress', () => {
    const dependencies = [
        { id: 'python', label: 'Python runtime', state: 'installed' as const, version: '3.13' },
        { id: 'yt-dlp', label: 'yt-dlp', state: 'installing' as const, progress: null },
        { id: 'node', label: 'Node.js', state: 'missing' as const },
    ];
    const labelWidth = Math.max(...dependencies.map((dependency) => stringWidth(dependency.label)));
    const labelColumns = dependencies.map((dependency, frame) => {
        const line = dependencyLine(dependency, labelWidth, frame)[0].text;
        return stringWidth(line.slice(0, line.indexOf(dependency.label)));
    });

    assert.deepEqual(labelColumns, [3, 3, 3]);
    assert.notEqual(
        dependencyLine(dependencies[1], labelWidth, 0)[1].text,
        dependencyLine(dependencies[1], labelWidth, 1)[1].text,
    );
});

test('renders the bundled YouTube runtime notice', async () => {
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
    const app = render(React.createElement(ExtensionPanelOverlay, {
        panel: {
            view: 'setup',
            title: 'YouTube setup',
            extensions: [],
            setup: {
                extension_id: 'youtube',
                page: 1,
                page_count: 1,
                title: 'YouTube built-in',
                body: 'yt-dlp and the PO Token Provider are bundled with Sonex.',
            },
        },
        selectedIndex: 0,
        width: 94,
    }), { stdout, stdin, debug: true, exitOnCtrlC: false });

    await new Promise((resolve) => setImmediate(resolve));
    const plain = stripAnsi(output);
    try {
        assert.match(plain, /yt-dlp and the PO Token Provider are bundled/);
    } finally {
        app.unmount();
        stdin.destroy();
        stdout.destroy();
    }
});

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
            action: 'enable',
            actions: ['quick_check', 'disable', 'prepare_reset'],
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

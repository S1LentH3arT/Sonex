import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';
import { stripVTControlCharacters } from 'node:util';

test('renders the Spotify exit warning directly below its title and keeps both choices', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { DynamicTail }] = await Promise.all([
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
        React.createElement(DynamicTail, {
            input: '',
            setInput: () => undefined,
            onSubmit: () => undefined,
            inputPlaceholder: '',
            inputFocus: false,
            inputRevision: 0,
            confirm: {
                id: 'provider-mode-exit',
                tool_name: 'provider_mode_exit',
                tool_args: { provider: 'spotify' },
                message: 'Exit Spotify Mode?',
                warning: "Running '/spotify' will exit Spotify Mode. Continue?",
                hide_hint: true,
                choices: [
                    { value: 'confirm_exit', label: 'Yes, I insist' },
                    { value: 'deny', label: 'No, return' },
                ],
            },
            confirmIndex: 0,
            spotifyMode: {
                enabled: true,
                device_id: 'desktop',
                device_name: 'Desktop',
            },
            providerMode: {
                provider: 'spotify',
                enabled: true,
            },
            spotifySetup: null,
            authSetup: null,
            modelStatus: null,
            slashSuggestions: [],
            slashIndex: 0,
            helpPanel: null,
            helpPanelIndex: 0,
            languagePanel: null,
            languagePanelIndex: 0,
            modelPanelIndex: 0,
            terminalColumns: 80,
            agentWorking: false,
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

    const plainOutput = stripVTControlCharacters(output);
    const lines = plainOutput.split('\n').map((line) => line.trim());
    const titleIndex = lines.indexOf('Exit Spotify Mode?');
    assert.notEqual(titleIndex, -1);
    assert.deepEqual(lines.slice(titleIndex, titleIndex + 5), [
        'Exit Spotify Mode?',
        "Warning: Running '/spotify' will exit Spotify Mode. Continue?",
        '',
        'Yes, I insist',
        'No, return',
    ]);

    const yellowAnsi = String.raw`\u001b\[(?:38;2;250;204;21|38;5;220)m`;
    assert.match(
        output,
        new RegExp(
            String.raw`\u001b\[1m${yellowAnsi}Warning: \u001b\[22m\u001b\[3mRunning '/spotify' will exit Spotify Mode\. Continue\?\u001b\[39m\u001b\[23m`,
        ),
    );
});

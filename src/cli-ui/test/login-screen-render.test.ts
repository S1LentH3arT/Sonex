import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';

import type { AuthSetupState } from '../src/types.js';

const stripAnsi = (value: string): string => value.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');

async function renderLoginScreen(authSetup: NonNullable<AuthSetupState>, selectedIndex = 0) {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { LoginScreen }] = await Promise.all([
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
    const stdin = new PassThrough() as PassThrough & {
        isTTY: boolean;
        setRawMode: (enabled: boolean) => void;
    };
    stdin.isTTY = true;
    stdin.setRawMode = () => undefined;
    const app = render(
        React.createElement(LoginScreen, {
            authSetup,
            selectedIndex,
            apiKeyInput: '',
            setApiKeyInput: () => undefined,
            onApiKeySubmit: () => undefined,
            inputFocus: false,
            language: 'en',
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
    return { frame: output, plain: stripAnsi(output) };
}

test('renders compact provider connection rows without lowercase aliases', async () => {
    const { frame, plain } = await renderLoginScreen({
        provider: 'openai',
        step: 'provider',
        title: 'Connect Sonex',
        message: 'Choose a provider.',
        active: true,
        providers: [
            { value: 'openai', label: 'OpenAI — Active', provider: 'openai', connected: true, connection_status: 'active' },
            { value: 'gemini', label: 'Google Gemini — Saved', provider: 'gemini', connected: true, connection_status: 'saved' },
            { value: 'openrouter', label: 'OpenRouter — Not connected', provider: 'openrouter', connected: false, connection_status: 'missing' },
        ],
    });

    assert.match(plain, /• OpenAI — Active/);
    assert.match(plain, /• Google Gemini — Saved/);
    assert.match(plain, /• OpenRouter — Not connected/);
    assert.doesNotMatch(plain, /Not connected\s+openai/);
    assert.doesNotMatch(plain, /Connected\s+gemini/);
    assert.match(plain, /↑\/↓ to navigate • Enter to continue/);
    assert.match(frame, /\u001b\[(?:38;2;29;185;84|38;5;78)m•/);
    assert.match(frame, /\u001b\[(?:38;2;128;135;145|38;5;145)m•/);
    assert.match(frame, /\u001b\[(?:38;2;239;68;68|38;5;203)m•/);
    assert.match(
        frame,
        /\u001b\[1m\u001b\[(?:38;2;128;135;145|38;5;145)m↑\/↓ to navigate • Enter to continue/,
    );
});

test('does not add account-status bullets to the Custom profile subpage', async () => {
    const { plain } = await renderLoginScreen({
        provider: 'custom',
        step: 'provider',
        title: 'Custom connections',
        message: 'Choose a saved connection.',
        active: true,
        providers: [
            { value: 'custom__local', label: 'Local — Connected' },
            { value: '__add_custom__', label: 'Add custom connection' },
        ],
    });

    assert.match(plain, /Local — Connected/);
    assert.doesNotMatch(plain, /• Local — Connected/);
});

test('renders the API key label, lowercase placeholder, and adjacent signup hint', async () => {
    const { frame, plain } = await renderLoginScreen({
        provider: 'deepseek',
        step: 'api_key',
        title: 'deepseek API key',
        message: 'Paste your deepseek API key.',
        prompt: 'API Key',
        placeholder: 'paste your key here',
        help_text: "Haven't got an API Key? Get one at https://platform.deepseek.com/.",
        mask: true,
        active: true,
    });

    assert.match(plain, /deepseek API key/);
    assert.match(plain, /API Key/);
    assert.match(plain, /paste your key here/);
    assert.match(plain, /Haven't got an API Key\? Get one at https:\/\/platform\.deepseek\.com\/\./);

    const rows = plain.split('\n');
    const inputRow = rows.findIndex((row) => row.includes('paste your key here'));
    const helpRow = rows.findIndex((row) => row.includes("Haven't got an API Key?"));
    assert.equal(helpRow, inputRow + 1);
    assert.match(
        frame,
        /\u001b\[3m\u001b\[(?:38;2;128;135;145|38;5;145)mHaven't got an API Key\?/,
    );
});

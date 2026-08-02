import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';

test('renders session token usage on two styled rows below the session id', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { HeaderFrame }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const stdout = new PassThrough() as PassThrough & {
        columns: number;
        rows: number;
        isTTY: boolean;
    };
    stdout.columns = 60;
    stdout.rows = 24;
    stdout.isTTY = true;
    let output = '';
    stdout.on('data', (chunk) => {
        output += chunk.toString();
    });
    const stdin = new PassThrough();
    const app = render(
        React.createElement(HeaderFrame, {
            authState: {
                ready: true,
                provider: 'openai',
                model: 'gpt-test',
                auth_type: 'oauth',
                credential_source: 'auth.json',
            },
            cwd: '/home/user/project',
            sessionId: 'session-1',
            tokenUsage: { inputTokens: 120, outputTokens: 34 },
            variant: 'compact',
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

    const grayAnsi = String.raw`\u001b\[(?:38;2;128;135;145|38;5;145)m`;
    const whiteAnsi = String.raw`\u001b\[(?:38;2;255;244;246|38;5;231)m`;
    assert.match(output, new RegExp(`${grayAnsi}usage:`));
    assert.match(output, new RegExp(`${whiteAnsi}input: 120 output: 34`));

    const plain = output.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');
    assert.ok(plain.indexOf('session id:') < plain.indexOf('session-1'));
    assert.ok(plain.indexOf('session-1') < plain.indexOf('usage:'));
    assert.ok(plain.indexOf('usage:') < plain.indexOf('input: 120 output: 34'));
});

test('places full-size usage details directly against the lower border', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { HeaderFrame }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const stdout = new PassThrough() as PassThrough & {
        columns: number;
        rows: number;
        isTTY: boolean;
    };
    stdout.columns = 100;
    stdout.rows = 24;
    stdout.isTTY = true;
    let output = '';
    stdout.on('data', (chunk) => {
        output += chunk.toString();
    });
    const stdin = new PassThrough();
    const app = render(
        React.createElement(HeaderFrame, {
            authState: {
                ready: true,
                provider: 'anthropic',
                model: 'claude-sonnet-4-6',
                model_label: 'Claude Sonnet 4.6',
                auth_type: 'api_key',
                credential_source: 'auth.json',
            },
            cwd: '/home/user/project',
            sessionId: 'session-2',
            tokenUsage: { inputTokens: 120, outputTokens: 34 },
            variant: 'full',
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

    const plain = output.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');
    assert.match(plain, /Claude Sonnet 4\.6 • API billing/);
    const usageRowIndex = plain.split('\n').findIndex((row) => row.includes('input: 120 output: 34'));
    const rows = plain.split('\n');
    assert.ok(usageRowIndex >= 0);
    assert.match(rows[usageRowIndex + 1] ?? '', /^╰.*╯/);
});

test('renders the logged-out identity warning in bold yellow', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { HeaderFrame }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const stdout = new PassThrough() as PassThrough & {
        columns: number;
        rows: number;
        isTTY: boolean;
    };
    stdout.columns = 60;
    stdout.rows = 24;
    stdout.isTTY = true;
    let output = '';
    stdout.on('data', (chunk) => {
        output += chunk.toString();
    });
    const stdin = new PassThrough();
    const app = render(
        React.createElement(HeaderFrame, {
            authState: {
                ready: false,
                provider: 'deepseek',
                model: 'deepseek-v4-flash',
                auth_type: 'none',
                credential_source: 'missing',
            },
            cwd: '/home/user/project',
            sessionId: 'session-3',
            tokenUsage: { inputTokens: 0, outputTokens: 0 },
            variant: 'compact',
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

    const plain = output.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');
    assert.match(plain, /deepseek-v4-flash • Not logged in/);
    assert.doesNotMatch(plain, /sign-in required/);
    assert.match(
        output,
        /\u001b\[1m\u001b\[(?:38;2;250;204;21|38;5;220)mNot logged in/,
    );
});

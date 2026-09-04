import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';
import { SONEX_MASCOT } from '../src/constants.js';
import { SONEX_LOGO } from '../src/sonex-logo.js';

test('leaves two blank rows between the startup banner and first message', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { CommittedTranscript }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const stdout = new PassThrough() as PassThrough & { columns: number; rows: number; isTTY: boolean };
    stdout.columns = 80;
    stdout.rows = 24;
    stdout.isTTY = true;
    let output = '';
    stdout.on('data', (chunk) => { output += chunk.toString(); });
    const stdin = new PassThrough();
    const presentation = { contentWidth: 76, headerVariant: 'mascot' as const, language: 'en' as const };
    const app = render(React.createElement(CommittedTranscript, { records: [
        {
            sequence: 1,
            item: {
                type: 'info_banner',
                authState: { ready: true, provider: 'openai', model: 'gpt-test', auth_type: 'oauth', credential_source: 'auth.json' },
                cwd: '/home/user/project',
                sessionId: 'session-1',
                showLogo: true,
            },
            presentation,
        },
        {
            sequence: 2,
            item: { type: 'message', role: 'user', content: 'hello' },
            presentation,
        },
    ] }), { stdout, stdin, debug: true, exitOnCtrlC: false });

    await new Promise((resolve) => setImmediate(resolve));
    app.unmount();
    stdin.destroy();
    stdout.destroy();

    const plain = output.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');
    const rows = plain.split('\n');
    const logoLastRow = rows.findIndex((row) => row.includes(SONEX_LOGO[SONEX_LOGO.length - 1]));
    const mascotFirstLine = SONEX_MASCOT[0].map((segment) => segment.text).join('');
    const mascotFirstRow = rows.findIndex((row) => row.includes(mascotFirstLine));
    const mascotLastLine = SONEX_MASCOT[SONEX_MASCOT.length - 1]
        .map((segment) => segment.text)
        .join('');
    const bannerLastRow = rows.findIndex((row) => row.includes(mascotLastLine));
    const messageRow = rows.findIndex((row) => row.includes('hello'));
    assert.ok(rows.some((row) => row.includes('session-1')));
    assert.ok(logoLastRow >= 0 && mascotFirstRow >= 0);
    assert.equal(mascotFirstRow - logoLastRow, 2);
    assert.equal(rows[logoLastRow + 1]?.trim(), '');
    assert.ok(bannerLastRow >= 0 && messageRow >= 0);
    assert.equal(messageRow - bannerLastRow, 3);
    assert.equal(rows[bannerLastRow + 1]?.trim(), '');
    assert.equal(rows[bannerLastRow + 2]?.trim(), '');
});

test('renders the session id without token usage rows', async () => {
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
    assert.ok(plain.indexOf('session id:') < plain.indexOf('session-1'));
    assert.doesNotMatch(plain, /usage:|input: 120|output: 34/);
    assert.doesNotMatch(plain, new RegExp(SONEX_LOGO[0]));
    assert.equal(
        SONEX_MASCOT.some((row) => plain.includes(row.map((segment) => segment.text).join(''))),
        false,
    );
});

test('renders the mascot and info without the session wordmark', async () => {
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
    stdout.columns = 140;
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
            variant: 'mascot',
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
    const rows = plain.split('\n');
    assert.match(plain, /Sonex CLI v0\.1\.0-alpha\.1/);
    assert.doesNotMatch(plain, /[╭╮╰╯│]/);
    assert.ok(SONEX_LOGO.every((logoRow) => rows.every((row) => !row.includes(logoRow))));
    for (const mascotRow of SONEX_MASCOT) {
        const text = mascotRow.map((segment) => segment.text).join('');
        assert.ok(rows.some((row) => row.includes(text)), `missing mascot row: ${text}`);
    }
});

test('renders the mascot tier without the SONEX wordmark', async () => {
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
    stdout.on('data', (chunk) => { output += chunk.toString(); });
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
            sessionId: 'session-medium',
            variant: 'mascot',
            language: 'en',
        }),
        { stdout, stdin, debug: true, exitOnCtrlC: false },
    );

    await new Promise((resolve) => setImmediate(resolve));
    app.unmount();
    stdin.destroy();
    stdout.destroy();

    const plain = output.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');
    assert.doesNotMatch(plain, new RegExp(SONEX_LOGO[0]));
    assert.ok(SONEX_MASCOT.every((row) => (
        plain.includes(row.map((segment) => segment.text).join(''))
    )));
    assert.match(plain, /gpt-test • OAuth/);
    assert.match(plain, /session-medium/);
});

test('renders the logo in mascot pale blue and removes only its color under NO_COLOR', async () => {
    process.env.FORCE_COLOR = '3';
    delete process.env.NO_COLOR;
    const [{ default: React }, { render }, { SonexLogo }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const renderLogo = async () => {
        const stdout = new PassThrough() as PassThrough & {
            columns: number;
            rows: number;
            isTTY: boolean;
        };
        stdout.columns = 80;
        stdout.rows = 12;
        stdout.isTTY = true;
        let output = '';
        stdout.on('data', (chunk) => { output += chunk.toString(); });
        const stdin = new PassThrough();
        const app = render(React.createElement(SonexLogo), {
            stdout,
            stdin,
            debug: true,
            exitOnCtrlC: false,
        });
        await new Promise((resolve) => setImmediate(resolve));
        app.unmount();
        stdin.destroy();
        stdout.destroy();
        return output;
    };

    const coloredOutput = await renderLogo();
    assert.match(coloredOutput, /\u001b\[38;(?:2;159;217;255|5;153)m/);
    assert.doesNotMatch(coloredOutput, /\u001b\[38;(?:2;59;130;246|5;75)m/);

    process.env.NO_COLOR = '1';
    const noColorOutput = await renderLogo();
    delete process.env.NO_COLOR;
    assert.doesNotMatch(noColorOutput, /\u001b\[(?:38;2|38;5);/);
    const plain = noColorOutput.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');
    assert.match(plain, new RegExp(SONEX_LOGO[0]));
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

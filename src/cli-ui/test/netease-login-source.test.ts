import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');

assert.match(typesSource, /type: "netease_login"/);
assert.match(typesSource, /type: "netease_login_input"; value: "__cancel__"/);
assert.match(appSource, /case "netease_login":/);
assert.match(appSource, /key\.escape[\s\S]*netease_login_input[\s\S]*__cancel__/);
assert.match(appSource, /connectionConfirm\?\.tool_name === "music_connection"[\s\S]*decision: "deny"/);
assert.match(componentSource, /export const NetEaseQrMessage/);
assert.match(componentSource, /Esc to play online/);
assert.match(componentSource, /Esc to cancel/);
assert.match(appSource, /type: "netease_qr"/);
assert.match(appSource, /evt\.output\.includes\("https:\/\/"\)/);

const test = (await import('node:test')).default;
const { PassThrough } = await import('node:stream');

test('renders the bridged terminal QR as a chat record with black and white cells', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { NetEaseQrMessage }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const stdout = new PassThrough() as InstanceType<typeof PassThrough> & {
        columns: number;
        rows: number;
        isTTY: boolean;
    };
    stdout.columns = 80;
    stdout.rows = 24;
    stdout.isTTY = true;
    let output = '';
    stdout.on('data', (chunk) => { output += chunk.toString(); });
    const stdin = new PassThrough();
    const app = render(React.createElement(NetEaseQrMessage, {
        item: {
            type: 'netease_qr',
            title: 'Connect NetEase',
            output: 'Scan:\n\u001b[47m  \u001b[40m  \u001b[0m',
            fallbackOnline: true,
        },
    }), { stdout, stdin, debug: true, exitOnCtrlC: false });

    await new Promise((resolve) => setImmediate(resolve));
    app.unmount();
    stdin.destroy();
    stdout.destroy();

    assert.match(output, /Scan:/);
    assert.match(output, /\u001b\[47m/);
    assert.match(output, /\u001b\[40m/);
});

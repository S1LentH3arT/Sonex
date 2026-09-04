import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';

import { chatDocumentSegments } from '../src/chat-document.js';

test('ChatDocument preserves list markers and semantic inline spans', () => {
    const segments = chatDocumentSegments({
        version: 1,
        blocks: [
            { type: 'heading', spans: [{ text: '推荐', style: 'plain' }] },
            { type: 'spacer' },
            {
                type: 'list_item',
                marker: '-',
                spans: [
                    { text: 'BB88', style: 'strong' },
                    { text: ' — ', style: 'plain' },
                    { text: '方大同', style: 'highlight' },
                ],
            },
        ],
    });

    assert.equal(segments.map((segment) => segment.text).join(''), '推荐\n\n- BB88 — 方大同');
    assert.deepEqual(
        segments.filter((segment) => !segment.text.includes('\n')).map((segment) => segment.style),
        ['heading', 'list_marker', 'strong', 'plain', 'highlight'],
    );
});

test('renders semantic Agent emphasis with accent, bold, and background ANSI', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { CommittedRecord }] = await Promise.all([
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
        React.createElement(CommittedRecord, {
            record: {
                sequence: 1,
                item: {
                    type: 'message',
                    role: 'agent',
                    content: '推荐\n\n- BB88 — 方大同',
                    document: {
                        version: 1,
                        blocks: [
                            { type: 'heading', spans: [{ text: '推荐', style: 'plain' }] },
                            { type: 'spacer' },
                            {
                                type: 'list_item',
                                marker: '-',
                                spans: [
                                    { text: 'BB88', style: 'strong' },
                                    { text: ' — ', style: 'plain' },
                                    { text: '方大同', style: 'highlight' },
                                ],
                            },
                        ],
                    },
                },
                presentation: {
                    contentWidth: 60,
                    headerVariant: 'mascot',
                    language: 'en',
                },
            },
        }),
        { stdout, stdin, debug: true, exitOnCtrlC: false },
    );

    await new Promise((resolve) => setImmediate(resolve));
    app.unmount();
    stdin.destroy();
    stdout.destroy();

    const blueAnsi = String.raw`\u001b\[(?:38;2;59;130;246|38;5;75)m`;
    const navyBackgroundAnsi = String.raw`\u001b\[(?:48;2;24;46;102|48;5;24)m`;
    assert.match(output, new RegExp(String.raw`\u001b\[1m${blueAnsi}推荐\u001b\[39m\u001b\[22m`));
    assert.match(output, new RegExp(String.raw`\u001b\[1m${blueAnsi}- BB88\u001b\[22m`));
    assert.match(output, new RegExp(`${navyBackgroundAnsi}`));
    assert.doesNotMatch(output, /\*\*|```|## /);
});

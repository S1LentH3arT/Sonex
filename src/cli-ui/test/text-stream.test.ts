import assert from 'node:assert/strict';
import test from 'node:test';

import { nextTextStreamOffset, streamedChatMessage, textStreamUnits } from '../src/text-stream.js';

test('streams short text one character at a time', () => {
    assert.equal(nextTextStreamOffset(0, 12), 1);
    assert.equal(nextTextStreamOffset(11, 12), 12);
});

test('streams long text in bounded chunks and clamps at completion', () => {
    assert.equal(nextTextStreamOffset(0, 600), 10);
    assert.equal(nextTextStreamOffset(595, 600), 600);
    assert.equal(nextTextStreamOffset(600, 600), 600);
});

test('keeps Unicode code points intact while revealing text', () => {
    assert.deepEqual(textStreamUnits('推荐 🎵'), ['推', '荐', ' ', '🎵']);
});

test('renders a plain partial answer while preserving final rich content for commit', () => {
    const item = {
        type: 'message' as const,
        role: 'agent' as const,
        content: 'Recommendation',
        theme: 'spotify' as const,
        segments: [{ text: 'Recommendation', style: 'heading' as const }],
        document: {
            version: 1 as const,
            blocks: [{ type: 'heading' as const, spans: [{ text: 'Recommendation', style: 'plain' as const }] }],
        },
    };

    assert.deepEqual(
        streamedChatMessage(item, textStreamUnits(item.content), 3),
        {
            ...item,
            content: 'Rec',
            segments: undefined,
            document: undefined,
        },
    );
    assert.equal(item.content, 'Recommendation');
    assert.ok(item.document);
});

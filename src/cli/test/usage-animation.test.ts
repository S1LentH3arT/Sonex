import assert from 'node:assert/strict';
import test from 'node:test';

import { nextAnimatedTokenCount, nextAnimatedTokenUsage } from '../src/usage-animation.js';

test('rapidly advances token counts without overshooting the target', () => {
    assert.equal(nextAnimatedTokenCount(0, 12_000), 3_000);
    assert.equal(nextAnimatedTokenCount(11_999, 12_000), 12_000);
    assert.equal(nextAnimatedTokenCount(12_000, 12_000), 12_000);
});

test('immediately follows a lower target such as a session reset', () => {
    assert.equal(nextAnimatedTokenCount(12_000, 0), 0);
    assert.deepEqual(
        nextAnimatedTokenUsage(
            { inputTokens: 120, outputTokens: 34 },
            { inputTokens: 126, outputTokens: 36 },
        ),
        { inputTokens: 122, outputTokens: 35 },
    );
});

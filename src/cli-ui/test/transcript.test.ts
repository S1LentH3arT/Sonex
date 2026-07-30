import assert from 'node:assert/strict';
import test from 'node:test';

import {
    allTranscriptItems,
    classifyServerEventForTranscript,
    createTranscriptState,
    transcriptReducer,
} from '../src/transcript.js';
import type { ChatMessageItem } from '../src/types.js';

const presentation = {
    contentWidth: 76,
    headerVariant: 'full',
    language: 'en',
} as const;

const message = (role: ChatMessageItem['role'], content: string): ChatMessageItem => ({
    type: 'message',
    role,
    content,
});

test('assigns monotonic sequence numbers without a transcript cap', () => {
    let state = createTranscriptState();
    const items = Array.from({ length: 120 }, (_, index) => message('agent', `message-${index}`));

    state = transcriptReducer(state, { type: 'commit', items, presentation });

    assert.equal(state.records.length, 120);
    assert.deepEqual(
        state.records.map((record) => record.sequence),
        Array.from({ length: 120 }, (_, index) => index),
    );
    assert.equal(state.nextSequence, 120);
});

test('commits a local prompt immediately and consumes its backend echo', () => {
    let state = createTranscriptState();
    state = transcriptReducer(state, { type: 'submitUser', item: message('user', 'play jazz'), presentation });
    state = transcriptReducer(state, { type: 'receiveUser', item: message('user', 'play jazz'), presentation });

    assert.deepEqual(allTranscriptItems(state), [message('user', 'play jazz')]);
    assert.deepEqual(state.pendingUserEchoes, {});
});

test('counts repeated identical prompts independently', () => {
    let state = createTranscriptState();
    state = transcriptReducer(state, { type: 'submitUser', item: message('user', 'again'), presentation });
    state = transcriptReducer(state, { type: 'submitUser', item: message('user', 'again'), presentation });
    state = transcriptReducer(state, { type: 'receiveUser', item: message('user', 'again'), presentation });

    assert.equal(state.records.length, 2);
    assert.equal(state.pendingUserEchoes.again, 1);

    state = transcriptReducer(state, { type: 'receiveUser', item: message('user', 'again'), presentation });
    assert.equal(state.records.length, 2);
    assert.deepEqual(state.pendingUserEchoes, {});
});

test('commits an unmatched server-originated user message', () => {
    const state = transcriptReducer(
        createTranscriptState(),
        { type: 'receiveUser', item: message('user', 'remote input'), presentation },
    );

    assert.deepEqual(allTranscriptItems(state), [message('user', 'remote input')]);
});

test('defers permanent records in alternate screen and flushes them in order', () => {
    let state = createTranscriptState();
    state = transcriptReducer(state, { type: 'commit', items: [message('agent', 'before')], presentation });
    state = transcriptReducer(state, { type: 'setSurface', surface: 'alternate' });
    const narrowPresentation = { ...presentation, contentWidth: 36 } as const;
    state = transcriptReducer(state, {
        type: 'commit',
        items: [message('agent', 'during')],
        presentation: narrowPresentation,
    });

    assert.deepEqual(state.records.map((record) => record.item), [message('agent', 'before')]);
    assert.deepEqual(
        state.deferredRecords.map((record) => record.item),
        [message('agent', 'during')],
    );
    assert.deepEqual(allTranscriptItems(state), [
        message('agent', 'before'),
        message('agent', 'during'),
    ]);

    state = transcriptReducer(state, { type: 'setSurface', surface: 'main' });
    assert.deepEqual(state.records.map((record) => record.item), [
        message('agent', 'before'),
        message('agent', 'during'),
    ]);
    assert.deepEqual(state.deferredRecords, []);
    assert.equal(state.records[1]?.presentation.contentWidth, 36);
});

test('drops the echo expectation when a local send fails', () => {
    let state = createTranscriptState();
    state = transcriptReducer(state, { type: 'submitUser', item: message('user', 'offline'), presentation });
    state = transcriptReducer(state, { type: 'rejectUserSend', content: 'offline' });
    state = transcriptReducer(state, { type: 'receiveUser', item: message('user', 'offline'), presentation });

    assert.deepEqual(allTranscriptItems(state), [
        message('user', 'offline'),
        message('user', 'offline'),
    ]);
});

test('treats object-prototype prompt names as ordinary echo keys', () => {
    let state = createTranscriptState();

    for (const content of ['constructor', 'toString', '__proto__']) {
        state = transcriptReducer(state, {
            type: 'submitUser',
            item: message('user', content),
            presentation,
        });
        state = transcriptReducer(state, {
            type: 'receiveUser',
            item: message('user', content),
            presentation,
        });
    }

    assert.deepEqual(state.pendingUserEchoes, {});
    assert.deepEqual(
        allTranscriptItems(state).map((item) => item.type === 'message' ? item.content : ''),
        ['constructor', 'toString', '__proto__'],
    );
});

test('classifies only chat and error server events as permanent candidates', () => {
    assert.equal(classifyServerEventForTranscript({ type: 'chat' }), 'chat');
    assert.equal(classifyServerEventForTranscript({ type: 'error' }), 'error');
    assert.equal(classifyServerEventForTranscript({ type: 'status' }), 'transient');
    assert.equal(classifyServerEventForTranscript({ type: 'activity' }), 'transient');
    assert.equal(classifyServerEventForTranscript({ type: 'track_panel' }), 'transient');
});

import assert from 'node:assert/strict';

import {
    CHAT_ERROR_MARKER_COLOR,
    CHAT_SYSTEM_MARKER_COLOR,
    CHAT_USER_MARKER_COLOR,
    CHAT_WARNING_MARKER_COLOR,
    resolveChatMarkerColor,
    resolveChatSubject,
    wrapChatMessageContent,
    wrapChatMessageSegments,
} from '../src/chat-message.js';
import { BORDER_BLUE, BORDER_BLUE_SOFT, SPOTIFY_GREEN, TOOL_NAVY, TOOL_VALUE } from '../src/constants.js';

assert.deepEqual(wrapChatMessageContent('hello', 20), ['hello']);
assert.deepEqual(wrapChatMessageContent('one\ntwo\nthree', 20), ['one', 'two', 'three']);
assert.deepEqual(wrapChatMessageContent('one\n\nthree\n', 20), ['one', '', 'three', '']);
assert.deepEqual(wrapChatMessageContent('abcdef', 3), ['abc', 'def']);
assert.deepEqual(wrapChatMessageContent('中文A', 3), ['中', '文A']);
assert.deepEqual(wrapChatMessageContent('🙂a', 2), ['🙂', 'a']);
assert.deepEqual(wrapChatMessageContent('界', 1), ['界']);
assert.deepEqual(wrapChatMessageContent('', 0), ['']);
assert.deepEqual(
    wrapChatMessageSegments([
        { text: 'Bash', style: 'tool_name' },
        { text: '  npm test\n      git status', style: 'tool_value' },
    ], 12),
    [
        [
            { text: 'Bash', style: 'tool_name' },
            { text: '  npm te', style: 'tool_value' },
        ],
        [{ text: 'st', style: 'tool_value' }],
        [{ text: '      git st', style: 'tool_value' }],
        [{ text: 'atus', style: 'tool_value' }],
    ],
);
assert.equal(TOOL_NAVY, '#182e66');
assert.equal(TOOL_VALUE, '#ffffff');

assert.equal(resolveChatMarkerColor('user', null, null), CHAT_USER_MARKER_COLOR);
assert.equal(resolveChatMarkerColor('user', 'spotify', 'error'), CHAT_USER_MARKER_COLOR);
assert.equal(resolveChatMarkerColor('agent', null, 'error'), CHAT_ERROR_MARKER_COLOR);
assert.equal(resolveChatMarkerColor('agent', 'spotify', 'error'), CHAT_ERROR_MARKER_COLOR);
assert.equal(resolveChatMarkerColor('agent', null, 'warning'), CHAT_WARNING_MARKER_COLOR);
assert.equal(CHAT_SYSTEM_MARKER_COLOR, '#c8a6ff');
assert.equal(BORDER_BLUE_SOFT, '#9fd9ff');
assert.equal(resolveChatMarkerColor('agent', null, 'system'), CHAT_SYSTEM_MARKER_COLOR);
assert.notEqual(resolveChatMarkerColor('agent', null, 'system'), BORDER_BLUE_SOFT);
assert.equal(resolveChatMarkerColor('agent', 'spotify', null), SPOTIFY_GREEN);
assert.equal(resolveChatMarkerColor('agent', null, null), BORDER_BLUE);

assert.equal(resolveChatSubject('user', null), 'User');
assert.equal(resolveChatSubject('user', 'error'), 'User');
assert.equal(resolveChatSubject('agent', null), 'Agent');
assert.equal(resolveChatSubject('agent', 'system'), 'System');
assert.equal(resolveChatSubject('agent', 'warning'), 'Warning');
assert.equal(resolveChatSubject('agent', 'error'), 'Caution');

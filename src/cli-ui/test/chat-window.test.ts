import assert from 'node:assert/strict';

import { getVisibleChatWindow } from '../src/chat-window.js';
import type { ChatItem } from '../src/types.js';

const messages: ChatItem[] = [
    { role: 'user', content: 'short' },
    { role: 'agent', content: '中文消息需要按终端显示宽度换行' },
    { role: 'agent', content: 'A long error line that should wrap repeatedly in a narrow terminal.' },
    { role: 'user', content: 'line one\nline two' },
];

const wide = getVisibleChatWindow(messages, 9, 0, 40);
const narrow = getVisibleChatWindow(messages, 9, 0, 12);

assert.ok(wide.items.length > narrow.items.length);
assert.deepEqual(narrow.items.at(-1), messages.at(-1));
assert.equal(narrow.hasHiddenAbove, true);

const scrolled = getVisibleChatWindow(messages, 9, 1, 12);
assert.deepEqual(scrolled.items.at(-1), messages.at(-2));
assert.equal(scrolled.hasHiddenBelow, true);

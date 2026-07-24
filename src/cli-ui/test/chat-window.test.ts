import assert from 'node:assert/strict';

import { getVisibleChatWindow, trimList } from '../src/chat-window.js';
import type { ChatItem } from '../src/types.js';

const messages: ChatItem[] = [
    { type: 'message', role: 'user', content: 'short' },
    { type: 'message', role: 'agent', content: '中文消息需要按终端显示宽度换行' },
    { type: 'message', role: 'agent', content: 'A long error line that should wrap repeatedly in a narrow terminal.' },
    { type: 'message', role: 'user', content: 'line one\nline two' },
];

const wide = getVisibleChatWindow(messages, 9, 0, 40);
const narrow = getVisibleChatWindow(messages, 9, 0, 12);

assert.ok(wide.items.length > narrow.items.length);
assert.deepEqual(narrow.items.at(-1), messages.at(-1));
assert.equal(narrow.hasHiddenAbove, true);

const scrolled = getVisibleChatWindow(messages, 9, 1, 12);
assert.deepEqual(scrolled.items.at(-1), messages.at(-2));
assert.equal(scrolled.hasHiddenBelow, true);

const banner: ChatItem = {
    type: 'info_banner',
    authState: {
        ready: true,
        provider: 'openai',
        model: 'gpt-test',
        auth_type: 'oauth',
        credential_source: 'auth.json',
    },
    cwd: '/home/user/project',
};
const mixed: ChatItem[] = [
    banner,
    { type: 'message', role: 'agent', content: 'latest' },
];

assert.deepEqual(getVisibleChatWindow(mixed, 10, 0, 40, 'compact').items, mixed);
assert.deepEqual(getVisibleChatWindow(mixed, 10, 0, 40, 'full').items, [mixed[1]]);

const bannerWithNewMessages: ChatItem[] = [
    banner,
    ...Array.from({ length: 5 }, (_, index): ChatItem => ({
        type: 'message',
        role: 'agent',
        content: `message ${index + 1}`,
    })),
];
const bottomWindow = getVisibleChatWindow(bannerWithNewMessages, 10, 0, 40, 'full');
assert.equal(bottomWindow.items.includes(banner), false);
assert.equal(bottomWindow.hasHiddenAbove, true);

const historyWindow = getVisibleChatWindow(bannerWithNewMessages, 10, 5, 40, 'full');
assert.deepEqual(historyWindow.items, [banner]);
assert.equal(historyWindow.hasHiddenBelow, true);

const capped = trimList(bannerWithNewMessages, 5);
assert.equal(capped.length, 5);
assert.equal(capped.includes(banner), false);

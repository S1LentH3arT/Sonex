import assert from 'node:assert/strict';

import {
    chatMessagesForTranscript,
    createInfoBannerItem,
    formatWorkingDirectory,
} from '../src/info-banner.js';
import type { AuthRuntimeState, ChatItem } from '../src/types.js';

const authState: AuthRuntimeState = {
    ready: true,
    provider: 'openai',
    model: 'gpt-before',
    auth_type: 'oauth',
    credential_source: 'auth.json',
};
const snapshot = createInfoBannerItem(authState, '/home/user/project', 'session-1');
const startupSnapshot = createInfoBannerItem(
    authState,
    '/home/user/project',
    'session-1',
    { showLogo: true },
);

authState.model = 'gpt-after';
assert.equal(snapshot.authState.model, 'gpt-before');
assert.equal(snapshot.cwd, '/home/user/project');
assert.equal(snapshot.sessionId, 'session-1');
assert.equal(snapshot.showLogo, false);
assert.equal(startupSnapshot.showLogo, true);
assert.equal('tokenUsage' in snapshot, false);

assert.equal(formatWorkingDirectory('/home/user', '/home/user'), '~');
assert.equal(formatWorkingDirectory('/home/user/project', '/home/user'), '~/project');
assert.equal(formatWorkingDirectory('/home/username/project', '/home/user'), '/home/username/project');
assert.equal(formatWorkingDirectory('C:\\Users\\Alice\\project', 'C:\\Users\\Alice'), '~\\project');
assert.equal(formatWorkingDirectory('D:\\music', 'C:\\Users\\Alice'), 'D:\\music');

const items: ChatItem[] = [
    snapshot,
    { type: 'message', role: 'user', content: '/info' },
    { type: 'message', role: 'agent', content: 'hello', theme: 'spotify', tone: 'error' },
];
assert.deepEqual(chatMessagesForTranscript(items), [
    { role: 'user', content: '/info' },
    { role: 'agent', content: 'hello', theme: 'spotify' },
]);

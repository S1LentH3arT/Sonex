import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.match(source, /const COMMAND_LIST_LABEL_WIDTH = 10/);
assert.match(source, /padEnd\(COMMAND_LIST_LABEL_WIDTH, " "\)/);

const slashStart = source.indexOf('const SlashCommandList =');
const helpStart = source.indexOf('const HelpPanel =', slashStart);
const slashSource = source.slice(slashStart, helpStart);
assert.doesNotMatch(slashSource, /command\.usage/);
assert.doesNotMatch(slashSource, /formatCommandListLabel\(command\)[\s\S]{0,120}> - </);

const chatStart = source.indexOf('const ChatBubble =', helpStart);
const helpSource = source.slice(helpStart, chatStart);
assert.doesNotMatch(helpSource, /command\.usage/);
assert.doesNotMatch(helpSource, /formatCommandListLabel\(command\)[\s\S]{0,120}> - </);
assert.match(helpSource, /borderStyle="single"/);

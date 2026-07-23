import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const promptStart = source.indexOf('const PromptInput =');
const promptEnd = source.indexOf('\ntype ChoicePanelRow =', promptStart);
assert.ok(promptStart >= 0);
assert.ok(promptEnd > promptStart);

const promptBody = source.slice(promptStart, promptEnd);
assert.match(source, /import \{ Box, Text, Transform, measureElement \} from 'ink';/);
assert.match(source, /import \{ hideInputCursor \} from '\.\/input-cursor\.js';/);
assert.match(source, /const INPUT_CURSOR_BLINK_INTERVAL_MS = 500;/);
assert.match(promptBody, /const \[cursorVisible, setCursorVisible\] = React\.useState\(true\);/);
assert.match(promptBody, /setCursorVisible\(true\);/);
assert.match(promptBody, /if \(!focus\) return;/);
assert.match(promptBody, /setInterval\([\s\S]*setCursorVisible\(\(visible\) => !visible\)[\s\S]*INPUT_CURSOR_BLINK_INTERVAL_MS/);
assert.match(promptBody, /return \(\) => clearInterval\(timer\);/);
assert.match(promptBody, /\}, \[focus, input, inputRevision\]\);/);
assert.match(promptBody, /<Transform transform=\{\(output\) => cursorVisible \? output : hideInputCursor\(output\)\}>/);
assert.match(promptBody, /focus=\{focus\}/);
assert.doesNotMatch(promptBody, /showCursor=\{cursorVisible\}/);

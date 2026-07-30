import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const cursorSource = readFileSync(new URL('../src/input-cursor.ts', import.meta.url), 'utf8');
const promptStart = source.indexOf('const PromptInput =');
const promptEnd = source.indexOf('\ntype ConfirmChoiceLabel =', promptStart);
assert.ok(promptStart >= 0);
assert.ok(promptEnd > promptStart);

const promptBody = source.slice(promptStart, promptEnd);
assert.match(source, /import \{ Box, Static, Text, Transform, measureElement \} from 'ink';/);
assert.match(
    source,
    /import \{ hideInputCursor, INPUT_CURSOR_BLINK_INTERVAL_MS \} from '\.\/input-cursor\.js';/,
);
assert.match(
    promptBody,
    /const \[cursorVisible, setCursorVisible\] = React\.useState\(true\)/,
);
assert.match(
    promptBody,
    /const timer = setInterval\(\(\) => setCursorVisible\(\(visible\) => !visible\), INPUT_CURSOR_BLINK_INTERVAL_MS\)/,
);
assert.match(promptBody, /return \(\) => clearInterval\(timer\)/);
assert.match(promptBody, /\[focus, input, inputRevision\]/);
assert.match(
    promptBody,
    /const visibleOutput = focus && cursorVisible \? output : hideInputCursor\(output\)/,
);
assert.match(source, /const fillPromptInputBackground = \(/);
assert.match(
    promptBody,
    /backgroundColor\s*\?\s*withTrueColorBackground\(filledOutput, backgroundColor\)\s*:\s*filledOutput/,
);
assert.match(promptBody, /focus=\{focus\}/);
assert.doesNotMatch(promptBody, /showCursor=/);
assert.match(cursorSource, /export const INPUT_CURSOR_BLINK_INTERVAL_MS = 500/);
assert.doesNotMatch(source, /enableTerminalInputCursorBlink/);
assert.match(
    appSource,
    /inputFocus=\{\(!confirm \|\| Boolean\(selectedConfirmInput\)\) && rawModeAvailable && !isExiting/,
);

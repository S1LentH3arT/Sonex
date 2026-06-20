import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.match(source, /const ConfirmChoiceRow =/);
const rowStart = source.indexOf('const ConfirmChoiceRow =');
const rowEnd = source.indexOf('const CompactConfirm =', rowStart);
const rowSource = source.slice(rowStart, rowEnd);

assert.match(rowSource, /flexDirection="row"/);
assert.match(source, /const isCancelChoice =/);
assert.match(rowSource, /isCancelChoice\(choice\) \? null : choice\.description/);
assert.match(rowSource, /\{description \? \(/);
assert.doesNotMatch(rowSource, /<Box key=\{choice\.value\} flexDirection="column">[\s\S]*choice\.description/);

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

const mascotStart = source.indexOf('const Mascot =');
const mascotEnd = source.indexOf('\n};', mascotStart);
assert.ok(mascotStart >= 0);
assert.ok(mascotEnd > mascotStart);

const mascotBody = source.slice(mascotStart, mascotEnd);
assert.match(mascotBody, /<Box width=\{16\} flexDirection="column" marginRight=\{3\}>/);
assert.match(mascotBody, /SONEX_MASCOT\.map/);

const headerStart = source.indexOf('export const HeaderFrame =');
const headerEnd = source.indexOf('\n};', headerStart);
assert.ok(headerStart >= 0);
assert.ok(headerEnd > headerStart);

const headerBody = source.slice(headerStart, headerEnd);
assert.equal((headerBody.match(/borderStyle="round"/g) ?? []).length, 2);
assert.equal((headerBody.match(/borderColor="#808791"/g) ?? []).length, 2);
assert.equal((headerBody.match(/<Text bold color=\{BORDER_BLUE\}>v\{APP_VERSION\}<\/Text>/g) ?? []).length, 2);
assert.equal((headerBody.match(/<Box height=\{1\} \/>/g) ?? []).length, 2);
assert.match(headerBody, /height=\{5\}/);
assert.doesNotMatch(headerBody, /tips\.placeholder/);

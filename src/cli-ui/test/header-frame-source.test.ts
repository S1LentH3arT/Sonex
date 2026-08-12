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
assert.doesNotMatch(headerBody, /borderStyle=|borderColor=/);
assert.equal((headerBody.match(/marginBottom=\{2\}/g) ?? []).length, 2);
assert.doesNotMatch(headerBody, /paddingX=/);
assert.equal((headerBody.match(/<Text bold color=\{BORDER_BLUE\}>v\{APP_VERSION\}<\/Text>/g) ?? []).length, 2);
assert.equal((headerBody.match(/<Box height=\{1\} \/>/g) ?? []).length, 2);
assert.equal(
    (headerBody.match(/<Text color="#facc15" bold>Not logged in<\/Text>/g) ?? []).length,
    2,
);
assert.match(headerBody, /authState\.ready[\s\S]*\? formatAuthLabel\(authState\)/);
assert.match(headerBody, /sessionId: string \| null/);
assert.doesNotMatch(headerBody, /tokenUsage|usage:|input:|output:/);
assert.doesNotMatch(headerBody, /height=\{8\}|minHeight=/);
assert.equal((headerBody.match(/\{displayCwd\}/g) ?? []).length, 2);
assert.equal((headerBody.match(/session id:/g) ?? []).length, 2);
assert.equal((headerBody.match(/\{sessionId\}/g) ?? []).length, 2);
assert.equal(
    (headerBody.match(/<Text color="#808791">session id:<\/Text>/g) ?? []).length,
    2,
);
assert.equal(
    (headerBody.match(/<Text color="#fff4f6" wrap="truncate-end">\{sessionId\}<\/Text>/g) ?? []).length,
    2,
);
assert.equal(
    (headerBody.match(/<Text color="#fff4f6"(?: wrap="truncate-end")?>\{displayCwd\}<\/Text>/g) ?? []).length,
    2,
);
assert.doesNotMatch(headerBody, /~\/dev\/sonex/);
assert.doesNotMatch(headerBody, /tips\.placeholder/);

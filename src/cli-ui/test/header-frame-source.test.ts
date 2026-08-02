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
assert.equal(
    (headerBody.match(/<Text color="#facc15" bold>Not logged in<\/Text>/g) ?? []).length,
    2,
);
assert.match(headerBody, /authState\.ready[\s\S]*\? formatAuthLabel\(authState\)/);
assert.match(headerBody, /sessionId: string \| null/);
assert.match(headerBody, /tokenUsage: SessionTokenUsage/);
assert.equal((headerBody.match(/height=\{10\}/g) ?? []).length, 2);
assert.doesNotMatch(headerBody, /minHeight=/);
assert.equal((headerBody.match(/\{displayCwd\}/g) ?? []).length, 2);
assert.equal((headerBody.match(/session id:/g) ?? []).length, 2);
assert.equal((headerBody.match(/\{sessionId\}/g) ?? []).length, 2);
assert.equal((headerBody.match(/usage:/g) ?? []).length, 2);
assert.equal(
    (headerBody.match(/<Text color="#808791">session id:<\/Text>/g) ?? []).length,
    2,
);
assert.equal(
    (headerBody.match(/<Text color="#fff4f6" wrap="truncate-end">\{sessionId\}<\/Text>/g) ?? []).length,
    2,
);
assert.equal(
    (headerBody.match(/<Text color="#808791">usage:<\/Text>/g) ?? []).length,
    2,
);
assert.equal(
    (headerBody.match(/<Text color="#fff4f6" wrap="truncate-end">input: \{tokenUsage\.inputTokens\} output: \{tokenUsage\.outputTokens\}<\/Text>/g) ?? []).length,
    2,
);
assert.equal(
    (headerBody.match(/<Text color="#fff4f6"(?: wrap="truncate-end")?>\{displayCwd\}<\/Text>/g) ?? []).length,
    2,
);
assert.doesNotMatch(headerBody, /~\/dev\/sonex/);
assert.doesNotMatch(headerBody, /tips\.placeholder/);

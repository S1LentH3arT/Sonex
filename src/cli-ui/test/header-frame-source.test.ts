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
assert.doesNotMatch(headerBody, /SonexLogo|SONEX_LOGO/);
assert.doesNotMatch(headerBody, /borderStyle=|borderColor=/);
assert.equal((headerBody.match(/marginBottom=\{2\}/g) ?? []).length, 2);
assert.doesNotMatch(headerBody, /paddingX=/);
assert.equal((headerBody.match(/<Text bold color=\{BORDER_BLUE\}>v\{APP_VERSION\}<\/Text>/g) ?? []).length, 1);
assert.equal((headerBody.match(/<Box height=\{1\} \/>/g) ?? []).length, 1);
assert.equal(
    (headerBody.match(/<Text color="#facc15" bold>Not logged in<\/Text>/g) ?? []).length,
    1,
);
assert.match(headerBody, /authState\.ready[\s\S]*\? formatAuthLabel\(authState\)/);
assert.match(headerBody, /sessionId: string \| null/);
assert.doesNotMatch(headerBody, /tokenUsage|usage:|input:|output:/);
assert.doesNotMatch(headerBody, /height=\{8\}|minHeight=/);
assert.equal((headerBody.match(/\{displayCwd\}/g) ?? []).length, 1);
assert.equal((headerBody.match(/session id:/g) ?? []).length, 1);
assert.equal((headerBody.match(/\{sessionId\}/g) ?? []).length, 1);
assert.equal(
    (headerBody.match(/<Text color=\{PANEL_SECONDARY\}>session id:<\/Text>/g) ?? []).length,
    1,
);
assert.equal(
    (headerBody.match(/<Text color=\{PANEL_PRIMARY\} wrap="truncate-end">\{sessionId\}<\/Text>/g) ?? []).length,
    1,
);
assert.equal(
    (headerBody.match(/<Text color=\{PANEL_PRIMARY\}(?: wrap="truncate-end")?>\{displayCwd\}<\/Text>/g) ?? []).length,
    1,
);
assert.doesNotMatch(headerBody, /~\/dev\/sonex/);
assert.doesNotMatch(headerBody, /tips\.placeholder/);

const committedRecordStart = source.indexOf('export const CommittedRecord =');
const committedRecordEnd = source.indexOf('export const CommittedTranscript =', committedRecordStart);
const committedRecordBody = source.slice(committedRecordStart, committedRecordEnd);
assert.match(
    committedRecordBody,
    /record\.item\.type === "info_banner" \? \([\s\S]*<HeaderFrame[\s\S]*variant=\{record\.presentation\.headerVariant\}/,
);
assert.match(committedRecordBody, /<HeaderFrame[\s\S]*variant=\{record\.presentation\.headerVariant\}/);

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const componentsSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

const componentSlice = (startMarker: string, endMarker: string): string => {
    const start = componentsSource.indexOf(startMarker);
    const end = componentsSource.indexOf(endMarker, start);
    assert.ok(start >= 0, `missing ${startMarker}`);
    assert.ok(end > start, `missing ${endMarker}`);
    return componentsSource.slice(start, end);
};

test('renders committed records through Ink Static', () => {
    assert.match(componentsSource, /import \{[^}]*Static[^}]*\} from 'ink';/s);
    assert.match(componentsSource, /export const CommittedTranscript/);
    assert.match(componentsSource, /<Static items=\{records\}>/);
    assert.match(componentsSource, /<CommittedRecord[\s\S]*key=\{record\.sequence\}/);
});

test('keeps the main live tail separate from permanent records', () => {
    const dynamicTailSource = componentSlice('export const DynamicTail', 'function useVisibleSnapshotOnRevision');

    assert.doesNotMatch(dynamicTailSource, /ChatPane|committedRecords|Static/);
    assert.match(dynamicTailSource, /<InputDock/);
});

test('removes the measured virtual conversation components', () => {
    assert.doesNotMatch(componentsSource, /const ChatPane/);
    assert.doesNotMatch(componentsSource, /const ConversationColumn/);
    assert.doesNotMatch(componentsSource, /getVisibleChatWindow|scrollOffset/);
});

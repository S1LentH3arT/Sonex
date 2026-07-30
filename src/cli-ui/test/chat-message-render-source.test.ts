import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const componentsSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

const chatBubbleStart = componentsSource.indexOf('const ChatBubble =');
const chatBubbleEnd = componentsSource.indexOf('export const CommittedRecord =', chatBubbleStart);
const chatBubbleSource = componentsSource.slice(chatBubbleStart, chatBubbleEnd);
const committedRecordStart = chatBubbleEnd;
const committedTranscriptStart = componentsSource.indexOf('export const CommittedTranscript =', committedRecordStart);
const committedTranscriptEnd = componentsSource.indexOf('const localizeTrackPanelTitle', committedTranscriptStart);
const committedRecordSource = componentsSource.slice(committedRecordStart, committedTranscriptStart);
const committedTranscriptSource = componentsSource.slice(committedTranscriptStart, committedTranscriptEnd);

test('ChatBubble renders spaced physical-line markers without an Ink border', () => {
    assert.ok(chatBubbleStart >= 0);
    assert.ok(chatBubbleEnd > chatBubbleStart);
    assert.match(chatBubbleSource, /wrapChatMessageContent\(content, contentWidth\)/);
    assert.match(chatBubbleSource, /resolveChatMarkerColor\(role, theme, tone\)/);
    assert.match(chatBubbleSource, /resolveChatSubject\(role, tone\)/);
    assert.match(
        chatBubbleSource,
        /<Box marginBottom=\{1\} flexDirection="column" width="100%">\s*<Text bold color=\{markerColor\}>\{subject\}<\/Text>\s*\{lines\.map/,
    );
    assert.match(chatBubbleSource, /index === lines\.length - 1 \? "└" : "│"/);
    assert.match(
        chatBubbleSource,
        /const color = theme === "muted" && !isUser \? "#9ca3af" : isUser \? "#fff6f8" : "#f6e9ee";/,
    );
    assert.doesNotMatch(
        chatBubbleSource,
        /theme === "spotify" && !isUser \? SPOTIFY_GREEN/,
    );
    assert.match(
        chatBubbleSource,
        /<Text color=\{markerColor\}>\{marker\}<\/Text>\s*<Text color=\{color\}>\{` \$\{line\}`\}<\/Text>/,
    );
    assert.doesNotMatch(chatBubbleSource, /\{marker\} \{line\}/);
    assert.doesNotMatch(chatBubbleSource, /paddingX=|borderLeft=|borderColor=|borderStyle=/);
});

test('committed transcript appends records through Ink Static without a virtual viewport', () => {
    assert.ok(committedRecordStart >= 0);
    assert.ok(committedTranscriptStart > committedRecordStart);
    assert.ok(committedTranscriptEnd > committedTranscriptStart);
    assert.match(
        committedRecordSource,
        /record\.item\.type === "info_banner" \? \([\s\S]*<HeaderFrame[\s\S]*variant=\{record\.presentation\.headerVariant\}/,
    );
    assert.match(
        committedRecordSource,
        /record\.item\.type === "info_banner" \? \([\s\S]*<HeaderFrame[\s\S]*sessionId=\{record\.item\.sessionId\}/,
    );
    assert.match(
        committedRecordSource,
        /<ChatBubble[\s\S]*role=\{record\.item\.role\}[\s\S]*contentWidth=\{record\.presentation\.contentWidth\}[\s\S]*tone=\{record\.item\.tone\}/,
    );
    assert.match(committedTranscriptSource, /<Static items=\{records\}>/);
    assert.match(committedTranscriptSource, /key=\{record\.sequence\}/);
    assert.match(committedTranscriptSource, /<CommittedRecord[\s\S]*record=\{record\}/);
    assert.doesNotMatch(
        componentsSource,
        /ChatPane|getVisibleChatWindow|viewportRows|scrollOffset|emptyReserveRows/,
    );
});

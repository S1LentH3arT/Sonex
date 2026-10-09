import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentsSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');
const runnerSource = readFileSync(new URL('../../../src/ws/runner.py', import.meta.url), 'utf8');

assert.match(typesSource, /document\?: ChatDocument \| null; stream\?: boolean/);
assert.match(
    appSource,
    /if \(evt\.role === "agent" && evt\.stream\) \{[\s\S]*?startTextStream\(item\);[\s\S]*?return;/,
);
assert.match(appSource, /streamedChatMessage\([\s\S]*?activeTextStream\.visibleUnitCount/);
assert.match(appSource, /const commitItems[\s\S]*?finishActiveTextStream\(\);[\s\S]*?dispatchTranscript/);
assert.match(componentsSource, /streamingMessage[\s\S]*?<ChatBubble[\s\S]*?showDivider=\{false\}/);
assert.match(runnerSource, /append_agent_message\(plain, document=document, stream=True\)/);

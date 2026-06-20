import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

assert.match(source, /type ChoicePanelRow =/);
assert.match(source, /const ChoicePanel = \(/);
assert.match(source, /<Text color=\{rowColor\}>\{row\.label\}<\/Text>/);
assert.match(source, /<Text color=\{rowColor\}> - <\/Text>/);
assert.match(source, /<Text color=\{rowColor\}>\{row\.description\}<\/Text>/);

const compactConfirmStart = source.indexOf('const CompactConfirm =');
const languagePanelStart = source.indexOf('const LanguagePanel =');
const inputDockStart = source.indexOf('const InputDock =');
assert.ok(compactConfirmStart >= 0);
assert.ok(languagePanelStart > compactConfirmStart);
assert.ok(inputDockStart > languagePanelStart);

const compactConfirmBody = source.slice(compactConfirmStart, languagePanelStart);
const languagePanelBody = source.slice(languagePanelStart, inputDockStart);
const inputDockBody = source.slice(inputDockStart, source.indexOf('const ConversationColumn =', inputDockStart));

assert.match(compactConfirmBody, /<ChoicePanel/);
assert.match(languagePanelBody, /<ChoicePanel/);
assert.match(inputDockBody, /modelPanel/);
assert.match(inputDockBody, /<ChoicePanel[\s\S]*rows=\{modelPanel\.rows\}/);

assert.match(appSource, /const isModelPanelActive = authSetup\?\.active && authSetup\.step === "model"/);
assert.match(appSource, /const isLoginScreenActive = isGenericAuthSetup\(authSetup\) && !isModelPanelActive/);
assert.match(appSource, /completeSlashCommand\(selectedHelpCommand\)/);
assert.match(appSource, /send\(\{ type: "auth_setup_input", value: "__cancel__" \}\)/);

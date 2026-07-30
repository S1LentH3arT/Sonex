import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

assert.match(appSource, /const \[language\] = useState<UiLanguage>\(OFFICIAL_UI_LANGUAGE\)/);
assert.doesNotMatch(appSource, /loadUiLanguage|saveUiLanguage|setLanguage\(/);

const unknownBoundaryStart = appSource.indexOf('const isUnknownSlashInput =');
const unknownBoundaryEnd = appSource.indexOf('const selectedSlashCommand', unknownBoundaryStart);
assert.ok(unknownBoundaryStart >= 0);
assert.ok(unknownBoundaryEnd > unknownBoundaryStart);
const unknownBoundary = appSource.slice(unknownBoundaryStart, unknownBoundaryEnd);
assert.match(unknownBoundary, /activeRegion === "chat"/);
assert.match(unknownBoundary, /!confirm/);
assert.match(unknownBoundary, /!authSetup\?\.active/);
assert.match(unknownBoundary, /!spotifySetup\?\.active/);
assert.match(unknownBoundary, /slashSuggestions\.length === 0/);
assert.match(unknownBoundary, /!matchingSlashCommand\(input\)/);

const warningStart = appSource.indexOf('const appendUnknownCommandWarning =');
const warningEnd = appSource.indexOf('const inputPlaceholder', warningStart);
assert.ok(warningStart >= 0);
assert.ok(warningEnd > warningStart);
const warningHelper = appSource.slice(warningStart, warningEnd);
assert.match(warningHelper, /unknownSlashCommandMessage\(value\)/);
assert.match(warningHelper, /tone: "warning"/);

const submitUnknownStart = appSource.indexOf('text.startsWith("/") && !command');
const submitUnknownEnd = appSource.indexOf('command?.needsArgument', submitUnknownStart);
assert.ok(submitUnknownStart >= 0);
assert.ok(submitUnknownEnd > submitUnknownStart);
const submitUnknown = appSource.slice(submitUnknownStart, submitUnknownEnd);
assert.match(submitUnknown, /setInput\(""\)/);
assert.match(submitUnknown, /appendUnknownCommandWarning\(text\)/);

const tabUnknownStart = appSource.indexOf('if (!isUnknownSlashInput) return;');
const tabUnknownEnd = appSource.indexOf('if (!languagePanel?.active) return;', tabUnknownStart);
assert.ok(tabUnknownStart >= 0);
assert.ok(tabUnknownEnd > tabUnknownStart);
const tabUnknown = appSource.slice(tabUnknownStart, tabUnknownEnd);
assert.match(tabUnknown, /key\.tab \|\| inputKey === "\\t"/);
assert.match(tabUnknown, /appendUnknownCommandWarning\(input\)/);
assert.doesNotMatch(tabUnknown, /setInput\(/);

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const eventSource = readFileSync(new URL('../src/event-coordination.ts', import.meta.url), 'utf8');
const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');

assert.match(typesSource, /type:\s*"input_state"[\s\S]*disabled:\s*boolean[\s\S]*reason\?:\s*"recommendation"/);
assert.match(appSource, /const \{[\s\S]*recommendInputLocked \} = runtimeState/);
assert.match(appSource, /applyRuntimeEvent: \(event, raw\) => applyRuntimeAction\(\{ type: "event", event, rawEvent: raw \}\)/);
assert.match(eventSource, /case 'input_state':[\s\S]*event\.disabled && event\.reason === 'recommendation'/);
assert.match(eventSource, /bindings\.resetRecommendationInput\(\)/);
assert.match(appSource, /t\(language,\s*"input\.recommendPending"\)/);
const inputPlaceholderStart = appSource.indexOf('const inputPlaceholder =');
const inputMaskStart = appSource.indexOf('const inputMask =', inputPlaceholderStart);
assert.ok(inputPlaceholderStart >= 0);
assert.ok(inputMaskStart > inputPlaceholderStart);

const inputPlaceholderBody = appSource.slice(inputPlaceholderStart, inputMaskStart);
assert.match(inputPlaceholderBody, /selectedConfirmInput\.placeholder[\s\S]*authSetup\?\.active[\s\S]*spotifySetup\?\.active[\s\S]*recommendInputLocked[\s\S]*input\.recommendPending/);
assert.match(inputPlaceholderBody, /: "";/);
assert.doesNotMatch(inputPlaceholderBody, /input\.placeholder/);
assert.match(appSource, /if \(recommendInputLocked\) return;[\s\S]*const sanitized = value\.replace/);
assert.match(appSource, /if \(recommendInputLocked\) return;[\s\S]*const text = value\.trim\(\)/);
assert.match(appSource, /inputFocus=\{\(!confirm \|\| Boolean\(selectedConfirmInput\)\) && rawModeAvailable && !isExiting && !helpPanel && !languagePanel\?\.active && !themePanel\?\.active && !isModelPanelActive && !recommendInputLocked\}/);

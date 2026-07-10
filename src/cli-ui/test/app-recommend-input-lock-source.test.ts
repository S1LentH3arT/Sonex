import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const typesSource = readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');

assert.match(typesSource, /type:\s*"input_state"[\s\S]*disabled:\s*boolean[\s\S]*reason\?:\s*"recommendation"/);
assert.match(appSource, /const \[recommendInputLocked,\s*setRecommendInputLocked\]/);
assert.match(appSource, /case "input_state":[\s\S]*setRecommendInputLocked\(evt\.disabled && evt\.reason === "recommendation"\)/);
assert.match(appSource, /t\(language,\s*"input\.recommendPending"\)/);
assert.match(appSource, /if \(recommendInputLocked\) return;[\s\S]*const sanitized = value\.replace/);
assert.match(appSource, /if \(recommendInputLocked\) return;[\s\S]*const text = value\.trim\(\)/);
assert.match(appSource, /inputFocus=\{\(!confirm \|\| Boolean\(selectedConfirmInput\)\) && rawModeAvailable && !helpPanel && !languagePanel\?\.active && !isModelPanelActive && !recommendInputLocked\}/);

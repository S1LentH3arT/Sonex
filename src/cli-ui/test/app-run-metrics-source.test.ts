import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentsSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.equal(appSource.includes('formatElapsed'), false);
assert.equal(appSource.includes('showRunMetrics'), false);
assert.equal(appSource.includes('setElapsed'), false);
assert.equal(appSource.includes('setTokens'), false);
assert.equal(componentsSource.includes('showRunMetrics'), false);
assert.equal(componentsSource.includes('elapsed: string | null'), false);
assert.equal(componentsSource.includes('tokens: string | null'), false);

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const showErrorStart = source.indexOf('const showError = React.useCallback');
const showErrorEnd = source.indexOf('const inputPlaceholder', showErrorStart);

assert.ok(showErrorStart >= 0);
assert.ok(showErrorEnd > showErrorStart);

const showErrorSource = source.slice(showErrorStart, showErrorEnd);
assert.match(showErrorSource, /setChatItems/);
assert.equal(showErrorSource.includes('setActivityItems'), false);
assert.equal(showErrorSource.includes('setStatusText'), false);

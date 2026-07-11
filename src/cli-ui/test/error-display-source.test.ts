import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentsSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const showErrorStart = source.indexOf('const showError = React.useCallback');
const showErrorEnd = source.indexOf('const inputPlaceholder', showErrorStart);

assert.ok(showErrorStart >= 0);
assert.ok(showErrorEnd > showErrorStart);

const showErrorSource = source.slice(showErrorStart, showErrorEnd);
assert.match(showErrorSource, /setChatItems/);
assert.equal(showErrorSource.includes('setActivityItems'), false);
assert.equal(showErrorSource.includes('setStatusText'), false);

assert.match(source, /theme: evt\.theme/);
assert.match(source, /spotifyModeRef\.current\.enabled \? "spotify" : undefined/);
assert.match(componentsSource, /<ChatBubble[\s\S]*theme=\{chat\.theme\}/);
assert.match(componentsSource, /theme === "spotify" && !isUser \? SPOTIFY_GREEN/);
assert.match(componentsSource, /theme === "muted" && !isUser \? "#9ca3af"/);
assert.match(componentsSource, /theme === "muted" && !isUser \? "#6b7280"/);

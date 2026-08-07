import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentsSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const showErrorStart = source.indexOf('const showError = React.useCallback');
const showErrorEnd = source.indexOf('const inputPlaceholder', showErrorStart);

assert.ok(showErrorStart >= 0);
assert.ok(showErrorEnd > showErrorStart);

const showErrorSource = source.slice(showErrorStart, showErrorEnd);
assert.match(showErrorSource, /commitItems\(\[\{/);
assert.match(showErrorSource, /tone: "error"/);
assert.equal(showErrorSource.includes('setActivityItems'), false);
assert.equal(showErrorSource.includes('setStatusText'), false);

assert.match(source, /theme: evt\.theme/);
assert.match(source, /theme: evt\.theme,[\s\S]*tone: evt\.tone/);
assert.match(source, /spotifyModeRef\.current\.enabled \? "spotify" : undefined/);
assert.match(componentsSource, /<ChatBubble[\s\S]*theme=\{record\.item\.theme\}/);
assert.match(componentsSource, /tone=\{record\.item\.tone\}/);
assert.doesNotMatch(componentsSource, /theme === "spotify" && !isUser \? SPOTIFY_GREEN/);
assert.doesNotMatch(componentsSource, /theme === "muted" && !isUser \? "#9ca3af"/);
assert.match(componentsSource, /resolveChatMarkerColor\(role, theme, tone\)/);
assert.match(componentsSource, /resolveChatContentColor\(role, tone\)/);

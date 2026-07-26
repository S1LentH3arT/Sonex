import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, '../src/index.tsx'), 'utf8');
const appSource = fs.readFileSync(path.join(here, '../src/App.tsx'), 'utf8');

test('constructs, passes, and attaches one terminal surface controller', () => {
    assert.match(source, /new TerminalSurfaceController/);
    assert.match(source, /isTTY: process\.stdout\.isTTY === true/);
    assert.match(source, /terminalSurface\.prepare\(\)/);
    assert.match(source, /<App terminalSurface=\{terminalSurface\}/);
    assert.match(source, /terminalSurface\.attachRendererClear\(\(\) => app\.clear\(\)\)/);
});

test('cleans up if Ink rendering throws', () => {
    assert.match(
        source,
        /try\s*\{[\s\S]*render\([\s\S]*<App terminalSurface=\{terminalSurface\}[\s\S]*\);\s*\}\s*catch \(error\)\s*\{\s*terminalSurface\.dispose\(\);\s*throw error;/,
    );
});

test('uses one idempotent cleanup path for exit and signals', () => {
    assert.match(source, /const cleanup = \(\): void => terminalSurface\.dispose\(\)/);
    assert.match(source, /process\.once\('SIGINT', onSigint\)/);
    assert.match(source, /process\.once\('SIGTERM', onSigterm\)/);
    assert.match(source, /process\.exitCode = exitCode/);
    assert.match(source, /app\.unmount\(\)/);
    assert.match(source, /\.finally\(\(\) => \{\s*process\.removeListener/s);
    assert.match(
        source,
        /try\s*\{\s*app\.unmount\(\);\s*\}\s*finally\s*\{\s*cleanup\(\);\s*\}/,
    );
});

test('does not write startup terminal controls outside the controller', () => {
    assert.doesNotMatch(source, /process\.stdout\.write\(MOUSE_TRACKING_DISABLE\)/);
});

test('disables direct cursor writers for non-TTY output', () => {
    assert.match(
        appSource,
        /enabled:\s*stdout\.isTTY\s*===\s*true\s*&&\s*\(miniVisible\s*\|\|\s*spotifyImmersiveVisible\)/,
    );
    assert.match(
        appSource,
        /enabled:\s*stdout\.isTTY\s*===\s*true\s*&&\s*miniVisible/,
    );
});

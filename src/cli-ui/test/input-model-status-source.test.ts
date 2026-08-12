import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentsSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

const sliceComponent = (startMarker: string, endMarker: string): string => {
    const start = componentsSource.indexOf(startMarker);
    const end = componentsSource.indexOf(endMarker, start);
    assert.ok(start >= 0, `missing ${startMarker}`);
    assert.ok(end > start, `missing ${endMarker}`);
    return componentsSource.slice(start, end);
};

const inputDockSource = sliceComponent('const InputDock =', 'export const DynamicTail =');
const dynamicTailSource = sliceComponent('export const DynamicTail =', 'function useVisibleSnapshotOnRevision');
const dynamicShellSource = componentsSource.slice(
    componentsSource.indexOf('export const DynamicShell ='),
);

test('App derives and forwards the current model status', () => {
    assert.match(appSource, /import \{ formatModelStatus \} from '\.\/model-status\.js';/);
    assert.match(appSource, /const modelStatus = formatModelStatus\(authState, displayedTokenUsage\);/);
    assert.match(appSource, /<DynamicShell[\s\S]*modelStatus=\{modelStatus\}/);
});

test('conversation components forward only the model status presentation value', () => {
    assert.match(dynamicShellSource, /modelStatus,/);
    assert.match(dynamicShellSource, /modelStatus: string \| null;/);
    assert.match(dynamicShellSource, /<DynamicTail[\s\S]*modelStatus=\{modelStatus\}/);

    assert.match(dynamicTailSource, /modelStatus,/);
    assert.match(dynamicTailSource, /modelStatus: string \| null;/);
    assert.match(dynamicTailSource, /<InputDock[\s\S]*modelStatus=\{modelStatus\}/);
    assert.match(inputDockSource, /modelStatus,/);
    assert.match(inputDockSource, /modelStatus: string \| null;/);
});

test('input footer keeps one row and prioritizes the Spotify marker', () => {
    assert.match(
        inputDockSource,
        /<Box height=\{1\} paddingX=\{1\} flexDirection="row">[\s\S]*<Box flexGrow=\{1\} minWidth=\{0\}>/,
    );
    assert.match(
        inputDockSource,
        /modelStatus \? \(\s*<Text color="#808791" wrap="truncate-end">\{modelStatus\}<\/Text>/,
    );
    assert.match(
        inputDockSource,
        /<Box flexShrink=\{0\}>[\s\S]*<Text bold color=\{SPOTIFY_GREEN\}>\{spotifyModeBorderLabel\}<\/Text>/,
    );
    assert.doesNotMatch(inputDockSource, /justifyContent="flex-end"/);
    assert.doesNotMatch(inputDockSource, /\[Unknown\]|\{modelStatus \?\? ["']-["']\}/);
});

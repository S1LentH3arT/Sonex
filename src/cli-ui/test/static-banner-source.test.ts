import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.match(appSource, /import \{Box, Static, useApp, useInput, useStdin, useStdout\} from 'ink';/);
assert.match(appSource, /<Static items=\{bannerItems\}>/);
assert.match(appSource, /<HeaderFrame key=\{item\.id\} authState=\{item\.authState\}\/>/);
assert.match(appSource, /shouldAppendAuthBanner\(lastBannerSignatureRef\.current, nextAuthState\)/);

const dynamicShellBody = componentSource.slice(componentSource.indexOf('export const DynamicShell'));
assert.equal(dynamicShellBody.includes('<HeaderFrame'), false);
assert.equal(dynamicShellBody.includes('authState:'), false);

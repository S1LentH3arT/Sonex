import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.match(appSource, /import \{Box, Static, useApp, useInput, useStdin, useStdout\} from 'ink';/);
assert.match(appSource, /export function shouldRenderStaticBanner\(layout: ShellLayout\): boolean/);
assert.match(appSource, /return layout !== "miniPlayer"/);
assert.match(appSource, /shouldRenderStaticBanner\(resolvedLayout\) \? \(/);
assert.match(appSource, /<Static items=\{bannerItems\}>/);
assert.match(appSource, /<HeaderFrame key=\{item\.id\} authState=\{item\.authState\}\/>/);
assert.match(appSource, /shouldAppendAuthBanner\(lastBannerSignatureRef\.current, nextAuthState\)/);

const dynamicShellBody = componentSource.slice(componentSource.indexOf('export const DynamicShell'));
assert.equal(dynamicShellBody.includes('<HeaderFrame'), false);
assert.equal(dynamicShellBody.includes('authState:'), false);
assert.equal(dynamicShellBody.includes('width="100%" paddingX={1}'), false);
assert.match(dynamicShellBody, /const miniVisible = layout === "miniPlayer"/);
assert.match(dynamicShellBody, /const chatVisible = layout !== "miniPlayer"/);
assert.match(dynamicShellBody, /display=\{miniVisible \? "flex" : "none"\}/);
assert.match(dynamicShellBody, /display=\{chatVisible \? "flex" : "none"\}/);
assert.match(dynamicShellBody, /<PlayerPane[\s\S]*active=\{miniVisible\}/);
assert.match(dynamicShellBody, /<PlayerPane[\s\S]*active=\{showPlaybackSidebar\}/);

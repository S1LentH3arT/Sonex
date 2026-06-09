import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Defines the app source constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/static-banner-source.test.ts.
 */
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
/**
 * Defines the component source constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/static-banner-source.test.ts.
 */
const componentSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.match(appSource, /import \{ Box, Static, useApp, useInput, useStdin, useStdout \} from 'ink';/);
assert.match(appSource, /export function shouldRenderStaticBanner\(layout: ShellLayout\): boolean/);
assert.match(appSource, /return layout !== "miniPlayer"/);
assert.match(appSource, /shouldRenderStaticBanner\(resolvedLayout\) \? \(/);
assert.match(appSource, /<Static items=\{bannerItems\}>/);
assert.match(appSource, /<HeaderFrame key=\{item\.id\} authState=\{item\.authState\} \/>/);
assert.match(appSource, /shouldAppendAuthBanner\(lastBannerSignatureRef\.current, nextAuthState\)/);
/**
 * Defines the tab branch start constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/static-banner-source.test.ts.
 */
const tabBranchStart = appSource.indexOf('if (key.tab || inputKey === "\\t") {', appSource.indexOf('if (!player.is_playing'));
/**
 * Defines the tab branch end constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/static-banner-source.test.ts.
 */
const tabBranchEnd = appSource.indexOf('flashLayoutTransition();', tabBranchStart);
/**
 * Defines the tab branch constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/static-banner-source.test.ts.
 */
const tabBranch = appSource.slice(tabBranchStart, tabBranchEnd);
assert.ok(tabBranch.indexOf('clearTerminalForLayoutSwitch(stdout);') >= 0);
assert.ok(tabBranch.indexOf('clearTerminalForLayoutSwitch(stdout);') < tabBranch.indexOf('setSmallPlaybackFocus'));

/**
 * Defines the dynamic shell body constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/static-banner-source.test.ts.
 */
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

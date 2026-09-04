import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.match(appSource, /const \[shellState, dispatchShellState\] = React\.useReducer\(reduceShellState, initialShellState\)/);
assert.match(appSource, /const activeRegion = shellState\.region/);
assert.match(appSource, /const playbackSessionActive = shellState\.playbackSessionActive/);
assert.match(appSource, /const switchRegion = React\.useCallback/);
assert.match(appSource, /terminalSurface\.transition\(nextSurface, \(surface\) => \{[\s\S]*dispatchTranscript\(\{ type: "setSurface", surface \}\)[\s\S]*applyShellAction\(\{ type: "set_region", region: nextRegion \}\)/);
assert.doesNotMatch(appSource, /clearTerminalForLayoutSwitch|stdout\.write\(['"]\\u001B\[2J/);
assert.match(appSource, /reduceShellState\(shellStateRef\.current, \{[\s\S]*type: "player_event"/);
assert.match(appSource, /reduceShellState\(shellStateRef\.current, \{[\s\S]*type: "toggle_region"/);
assert.match(appSource, /switchRegion\("chat"\)/);
assert.doesNotMatch(appSource, /activeRegion === "chat" \? <HeaderFrame/);
assert.match(appSource, /const showFixedHeader = activeRegion === "chat" && authInterfaceActive/);
assert.match(appSource, /\{showFixedHeader \? \([\s\S]*<HeaderFrame[\s\S]*authState=\{authState\}/);
assert.match(appSource, /<CommittedTranscript[\s\S]*records=\{transcript\.records\}/);
assert.match(componentSource, /item\.type === "info_banner"[\s\S]*<HeaderFrame/);
assert.match(componentSource, /<Static items=\{records\}>/);
assert.equal(appSource.includes('resolveShellLayout'), false);
assert.equal(appSource.includes('smallPlaybackFocus'), false);
assert.equal(appSource.includes('shouldReturnToChatAfterSubmit'), false);

const dynamicShellBody = componentSource.slice(componentSource.indexOf('export const DynamicShell'));
assert.match(dynamicShellBody, /activeRegion === "miniPlayer"/);
assert.match(dynamicShellBody, /<MiniPlayerRegion/);
assert.match(dynamicShellBody, /<DynamicTail/);
assert.doesNotMatch(dynamicShellBody, /<ConversationRegion/);
assert.equal(dynamicShellBody.includes('display={miniVisible'), false);
assert.equal(dynamicShellBody.includes('display={chatVisible'), false);
assert.equal(dynamicShellBody.includes('showPlaybackSidebar'), false);
assert.equal(dynamicShellBody.includes('<QueuePane'), false);
assert.equal(dynamicShellBody.includes('layout === "full"'), false);

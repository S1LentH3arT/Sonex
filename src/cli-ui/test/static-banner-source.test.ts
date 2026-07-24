import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentSource = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.match(appSource, /const \[activeRegion, setActiveRegion\] = useState<ShellRegion>\("chat"\)/);
assert.match(appSource, /const \[playbackSessionActive, setPlaybackSessionActive\] = useState\(false\)/);
assert.match(appSource, /const switchRegion = React\.useCallback/);
assert.match(appSource, /clearTerminalForLayoutSwitch\(stdout\);[\s\S]*setActiveRegion\(nextRegion\)/);
assert.match(appSource, /resolveRegionAfterPlayerEvent/);
assert.match(appSource, /toggleShellRegion/);
assert.match(appSource, /switchRegion\("chat"\)/);
assert.doesNotMatch(appSource, /activeRegion === "chat" \? <HeaderFrame/);
assert.match(appSource, /const showFixedHeader = activeRegion === "chat" && authInterfaceActive/);
assert.match(appSource, /\{showFixedHeader \? \([\s\S]*<HeaderFrame authState=\{authState\}/);
assert.match(appSource, /authInterfaceActive \? chatItems\.filter\(isChatMessageItem\) : chatItems/);
assert.match(componentSource, /item\.type === "info_banner"[\s\S]*<HeaderFrame/);
assert.equal(appSource.includes('<Static'), false);
assert.equal(appSource.includes('resolveShellLayout'), false);
assert.equal(appSource.includes('smallPlaybackFocus'), false);
assert.equal(appSource.includes('shouldReturnToChatAfterSubmit'), false);

const dynamicShellBody = componentSource.slice(componentSource.indexOf('export const DynamicShell'));
assert.match(dynamicShellBody, /activeRegion === "miniPlayer"/);
assert.match(dynamicShellBody, /<MiniPlayerRegion/);
assert.match(dynamicShellBody, /<ConversationRegion/);
assert.equal(dynamicShellBody.includes('display={miniVisible'), false);
assert.equal(dynamicShellBody.includes('display={chatVisible'), false);
assert.equal(dynamicShellBody.includes('showPlaybackSidebar'), false);
assert.equal(dynamicShellBody.includes('<QueuePane'), false);
assert.equal(dynamicShellBody.includes('layout === "full"'), false);

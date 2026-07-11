import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const trackPanelInputStart = source.indexOf('useInput((inputKey, key) => {\n        if (!trackPanel');
const trackPanelInputEnd = source.indexOf('\n    }, { isActive: Boolean(trackPanel)', trackPanelInputStart);

assert.ok(trackPanelInputStart >= 0);
assert.ok(trackPanelInputEnd > trackPanelInputStart);

const trackPanelInput = source.slice(trackPanelInputStart, trackPanelInputEnd);
const escapeBranch = trackPanelInput.slice(trackPanelInput.indexOf('if (key.escape)'), trackPanelInput.indexOf('} else if (isTrackPanelQueueShortcut'));
const enterBranch = trackPanelInput.slice(trackPanelInput.indexOf('} else if (key.return'), trackPanelInput.indexOf('} else if (key.upArrow)'));

assert.match(trackPanelInput, /const dismissedTrackPanel = trackPanel\.panel/);
assert.match(escapeBranch, /dismissedTrackPanel === "playlist"/);
assert.match(escapeBranch, /t\(language, "trackPanel\.playlistHidden"\)/);
assert.match(escapeBranch, /t\(language, "trackPanel\.queueHidden"\)/);
assert.match(escapeBranch, /setTrackPanel\(null\)/);
assert.match(escapeBranch, /setTrackPanelIndex\(0\)/);
assert.match(escapeBranch, /setChatItems\(\(prev\) => \[\.\.\.prev, \{ role: "agent", content: hiddenMessage, theme: "muted" \}\]\)/);
assert.equal(enterBranch.includes('Hidden'), false);

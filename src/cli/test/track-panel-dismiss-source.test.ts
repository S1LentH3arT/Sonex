import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const trackPanelInputStart = source.indexOf('useInput((inputKey, key) => {\n        if (activeRegion !== "trackPanel"');
const trackPanelInputEnd = source.indexOf('\n    }, {\n        isActive: activeRegion === "trackPanel"', trackPanelInputStart);

assert.ok(trackPanelInputStart >= 0);
assert.ok(trackPanelInputEnd > trackPanelInputStart);

const trackPanelInput = source.slice(trackPanelInputStart, trackPanelInputEnd);
const escapeBranch = trackPanelInput.slice(trackPanelInput.indexOf('if (key.escape)'), trackPanelInput.indexOf('} else if (isTrackPanelQueueShortcut'));
const enterBranch = trackPanelInput.slice(trackPanelInput.indexOf('} else if (key.return'), trackPanelInput.indexOf('} else if (key.upArrow)'));

assert.match(escapeBranch, /setTrackPanel\(null\)/);
assert.match(escapeBranch, /setTrackPanelIndex\(0\)/);
assert.match(escapeBranch, /switchRegion\("chat"\)/);
assert.doesNotMatch(escapeBranch, /Hidden|appendPanelHiddenNotice/);
assert.equal(enterBranch.includes('Hidden'), false);

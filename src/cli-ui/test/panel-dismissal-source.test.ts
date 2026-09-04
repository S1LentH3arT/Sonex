import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

const sliceBetween = (startMarker: string, endMarker: string): string => {
    const start = source.indexOf(startMarker);
    const end = source.indexOf(endMarker, start + startMarker.length);
    assert.ok(start >= 0, `missing start marker: ${startMarker}`);
    assert.ok(end > start, `missing end marker: ${endMarker}`);
    return source.slice(start, end);
};

assert.doesNotMatch(source, /appendPanelHiddenNotice/);

const loginEscape = sliceBetween(
    'if (!isLoginScreenActive) return;',
    'if (!isModelPanelActive) return;',
);
assert.match(loginEscape, /key\.escape[\s\S]*send\(\{ type: "auth_setup_input", value: "__cancel__" \}\)/);

const modelEscape = sliceBetween(
    'if (!isModelPanelActive) return;',
    'if (!isSlashMenuActive || !selectedSlashCommand) return;',
);
assert.match(modelEscape, /key\.escape[\s\S]*send\(\{ type: "auth_setup_input", value: "__cancel__" \}\)/);

const slashEscape = sliceBetween(
    'if (!isSlashMenuActive || !selectedSlashCommand) return;',
    'if (!languagePanel?.active) return;',
);
assert.match(slashEscape, /key\.escape[\s\S]*setSlashMenuDismissedFor\(input\)/);
assert.doesNotMatch(slashEscape, /appendPanelHiddenNotice/);

const languageEscape = sliceBetween(
    'if (!languagePanel?.active) return;',
    'if (spotifySetup && spotifySetup.active === false && key.escape)',
);
assert.doesNotMatch(languageEscape, /panel\.languageHidden/);

const completedSetupEscape = sliceBetween(
    'if (spotifySetup && spotifySetup.active === false && key.escape)',
    'if (!confirm) return;',
);
assert.match(completedSetupEscape, /type: "clear_spotify_setup"/);
assert.match(completedSetupEscape, /type: "clear_auth_setup"/);
assert.doesNotMatch(completedSetupEscape, /panel\.(spotifySetupHidden|setupHidden)/);

const confirmEscape = sliceBetween(
    'if (!confirm) return;',
    'if (!helpPanel || confirm || isSlashMenuActive || languagePanel?.active) return;',
);
assert.match(confirmEscape, /key\.escape[\s\S]*decision: "deny"[\s\S]*setConfirm\(null\)/);
assert.doesNotMatch(confirmEscape, /panel\.confirmHidden/);

const helpEscape = sliceBetween(
    'if (!helpPanel || confirm || isSlashMenuActive || languagePanel?.active) return;',
    'if (activeRegion !== "trackPanel"',
);
assert.match(helpEscape, /key\.escape[\s\S]*setHelpPanel\(null\)/);
assert.doesNotMatch(helpEscape, /panel\.helpHidden/);

const trackPanelEscape = sliceBetween(
    'if (activeRegion !== "trackPanel"',
    'isActive: activeRegion === "trackPanel"',
);
assert.doesNotMatch(trackPanelEscape, /Hidden|appendPanelHiddenNotice/);

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

const noticeHelper = sliceBetween(
    'const appendPanelHiddenNotice = React.useCallback',
    'const inputPlaceholder =',
);
assert.match(
    noticeHelper,
    /commitItems\(\[\{[\s\S]*type: "message",[\s\S]*role: "agent",[\s\S]*content,[\s\S]*theme: "muted",[\s\S]*tone: "system"/,
);

const appleSetupEscape = sliceBetween(
    'if (!isAppleTokenSetupActive || !key.escape) return;',
    'if (!isLoginScreenActive || authSetup?.step === "api_key") return;',
);
assert.match(appleSetupEscape, /send\(\{ type: "auth_setup_input", value: "__cancel__" \}\)/);
assert.doesNotMatch(appleSetupEscape, /appendPanelHiddenNotice/);

const modelEscape = sliceBetween(
    'if (!isModelPanelActive) return;',
    'if (!isSlashMenuActive || !selectedSlashCommand) return;',
);
assert.match(modelEscape, /key\.escape[\s\S]*appendPanelHiddenNotice\(t\(language, "panel\.modelHidden"\)\)/);
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
assert.match(languageEscape, /key\.escape[\s\S]*appendPanelHiddenNotice\(t\(language, "panel\.languageHidden"\)\)/);

const completedSetupEscape = sliceBetween(
    'if (spotifySetup && spotifySetup.active === false && key.escape)',
    'if (!confirm) return;',
);
assert.match(completedSetupEscape, /setSpotifySetup\(null\)[\s\S]*panel\.spotifySetupHidden/);
assert.match(completedSetupEscape, /setAuthSetup\(null\)[\s\S]*panel\.setupHidden/);

const confirmEscape = sliceBetween(
    'if (!confirm) return;',
    'if (!helpPanel || confirm || isSlashMenuActive || languagePanel?.active) return;',
);
assert.match(confirmEscape, /key\.escape[\s\S]*decision: "deny"[\s\S]*setConfirm\(null\)[\s\S]*panel\.confirmHidden/);

const helpEscape = sliceBetween(
    'if (!helpPanel || confirm || isSlashMenuActive || languagePanel?.active) return;',
    'if (activeRegion !== "trackPanel"',
);
assert.match(helpEscape, /key\.escape[\s\S]*setHelpPanel\(null\)[\s\S]*panel\.helpHidden/);

const trackPanelEscape = sliceBetween(
    'if (activeRegion !== "trackPanel"',
    'isActive: activeRegion === "trackPanel"',
);
assert.match(trackPanelEscape, /key\.escape[\s\S]*trackPanel\.playlistHidden[\s\S]*trackPanel\.queueHidden/);
assert.match(trackPanelEscape, /appendPanelHiddenNotice\(hiddenMessage\)/);

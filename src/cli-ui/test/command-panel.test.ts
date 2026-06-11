import assert from 'node:assert/strict';

import { SLASH_COMMANDS } from '../src/constants.js';
import {
    HELP_PANEL_VISIBLE_COMMANDS,
    helpPanelCommands,
    visibleCommandWindow,
} from '../src/command-panel.js';

const allHelpCommands = helpPanelCommands(SLASH_COMMANDS);

assert.equal(HELP_PANEL_VISIBLE_COMMANDS, 8);
assert.deepEqual(
    allHelpCommands.map((command) => command.name),
    [...allHelpCommands.map((command) => command.name)].sort(),
);

assert.equal(visibleCommandWindow(allHelpCommands, 0, HELP_PANEL_VISIBLE_COMMANDS).items.length, 8);
assert.equal(visibleCommandWindow(allHelpCommands, 0, HELP_PANEL_VISIBLE_COMMANDS).items[0]?.name, "bye");
assert.equal(visibleCommandWindow(allHelpCommands, 8, HELP_PANEL_VISIBLE_COMMANDS).items.at(-1)?.name, allHelpCommands[8]?.name);

const slashSearch = SLASH_COMMANDS.find((command) => command.name === "search");
const helpSearch = allHelpCommands.find((command) => command.name === "search");
assert.equal(slashSearch?.description, "Search songs by keywords.");
assert.equal(helpSearch?.description, "Search songs by keywords.");

const helpPlay = allHelpCommands.find((command) => command.name === "play");
assert.equal(helpPlay?.usage, "/play <query/number>");
assert.equal(helpPlay?.description, "Play a song by query or result number.");

const helpRecommend = allHelpCommands.find((command) => command.name === "recommend");
assert.equal(helpRecommend?.description, "Recommend songs of preferred music taste.");

const helpPause = allHelpCommands.find((command) => command.name === "pause");
assert.equal(helpPause?.usage, "/pause");
assert.equal(helpPause?.description, "Pause current playback");

const helpVolume = allHelpCommands.find((command) => command.name === "volume");
assert.equal(helpVolume?.usage, "/volume <0-100>");
assert.equal(helpVolume?.description, "Set local playback volume");

const helpPlayer = allHelpCommands.find((command) => command.name === "player");
assert.equal(helpPlayer?.usage, "/player <auto|mpv|cvlc>");
assert.equal(helpPlayer?.description, "Set playback backend; auto uses mpv");

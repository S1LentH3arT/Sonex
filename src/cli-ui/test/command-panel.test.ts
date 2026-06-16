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

for (const hiddenName of ["pause", "volume", "progress", "stop"]) {
    assert.equal(SLASH_COMMANDS.find((command) => command.name === hiddenName), undefined);
    assert.equal(allHelpCommands.find((command) => command.name === hiddenName), undefined);
}

const helpPlayer = allHelpCommands.find((command) => command.name === "player");
assert.equal(helpPlayer?.usage, "/player <auto|mpv|cvlc>");
assert.equal(helpPlayer?.description, "Set playback backend; auto uses mpv");

const helpKeymap = allHelpCommands.find((command) => command.name === "keymap");
assert.equal(helpKeymap?.usage, "/keymap [on|off|toggle|status]");
assert.equal(helpKeymap?.description, "Toggle mini-player playback shortcuts");

const helpPlaylist = allHelpCommands.find((command) => command.name === "playlist");
assert.equal(helpPlaylist?.usage, "/playlist [name]|save [name]");
assert.equal(helpPlaylist?.description, "Browse or save playlists");

const helpQueue = allHelpCommands.find((command) => command.name === "queue");
assert.equal(helpQueue?.usage, "/queue");
assert.equal(helpQueue?.description, "Show recent songs");

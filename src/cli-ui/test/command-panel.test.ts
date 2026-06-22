import assert from 'node:assert/strict';

import { SLASH_COMMANDS } from '../src/constants.js';
import {
    HELP_PANEL_VISIBLE_COMMANDS,
    helpPanelCommands,
    selectedHelpPanelCommand,
    visibleCommandWindow,
} from '../src/command-panel.js';
import { SPOTIFY_MODE_COMMAND_NAMES, spotifyModeSlashCommands } from '../src/commands.js';

const allHelpCommands = helpPanelCommands(SLASH_COMMANDS);
const localizedHelpCommands = helpPanelCommands([
    {
        name: "player",
        usage: "/player",
        description: "选择播放后端",
    },
    {
        name: "help",
        usage: "/help",
        description: "显示命令列表",
    },
]);

assert.equal(HELP_PANEL_VISIBLE_COMMANDS, 8);
assert.deepEqual(
    allHelpCommands.map((command) => command.name),
    [...allHelpCommands.map((command) => command.name)].sort(),
);

assert.equal(visibleCommandWindow(allHelpCommands, 0, HELP_PANEL_VISIBLE_COMMANDS).items.length, 8);
assert.equal(visibleCommandWindow(allHelpCommands, 0, HELP_PANEL_VISIBLE_COMMANDS).items[0]?.name, "bye");
assert.equal(visibleCommandWindow(allHelpCommands, 8, HELP_PANEL_VISIBLE_COMMANDS).items.at(-1)?.name, allHelpCommands[8]?.name);
assert.equal(selectedHelpPanelCommand(allHelpCommands, 0)?.name, "bye");
assert.equal(selectedHelpPanelCommand(allHelpCommands, 999)?.name, allHelpCommands.at(-1)?.name);
assert.equal(selectedHelpPanelCommand([], 0), null);

const slashSearch = SLASH_COMMANDS.find((command) => command.name === "search");
const helpSearch = allHelpCommands.find((command) => command.name === "search");
assert.equal(slashSearch, undefined);
assert.equal(helpSearch, undefined);

const slashPlay = SLASH_COMMANDS.find((command) => command.name === "play");
const helpPlay = allHelpCommands.find((command) => command.name === "play");
assert.equal(slashPlay, undefined);
assert.equal(helpPlay, undefined);

const helpRecommend = allHelpCommands.find((command) => command.name === "recommend");
assert.equal(helpRecommend?.description, "recommend songs of preferred music taste");

for (const hiddenName of ["pause", "volume", "progress", "stop"]) {
    assert.equal(SLASH_COMMANDS.find((command) => command.name === hiddenName), undefined);
    assert.equal(allHelpCommands.find((command) => command.name === hiddenName), undefined);
}

const helpPlayer = allHelpCommands.find((command) => command.name === "player");
const slashPlayer = SLASH_COMMANDS.find((command) => command.name === "player");
assert.equal(helpPlayer?.usage, "/player");
assert.equal(helpPlayer?.description, "choose playback backend from a panel");
assert.equal(slashPlayer?.needsArgument, false);
assert.equal(localizedHelpCommands.find((command) => command.name === "help")?.description, "显示命令列表");
assert.equal(localizedHelpCommands.find((command) => command.name === "player")?.description, "选择播放后端");

const helpKeymap = allHelpCommands.find((command) => command.name === "keymap");
assert.equal(helpKeymap?.usage, "/keymap [on|off|toggle|status]");
assert.equal(helpKeymap?.description, "toggle mini-player playback shortcuts");

const helpLang = allHelpCommands.find((command) => command.name === "lang");
assert.equal(helpLang?.usage, "/lang");
assert.equal(helpLang?.description, "choose the TUI display language");

const helpPlaylist = allHelpCommands.find((command) => command.name === "playlist");
assert.equal(helpPlaylist?.usage, "/playlist [name]|save [name]");
assert.equal(helpPlaylist?.description, "browse or save playlists");

const helpQueue = allHelpCommands.find((command) => command.name === "queue");
assert.equal(helpQueue?.usage, "/queue");
assert.equal(helpQueue?.description, "show playback queue");

assert.deepEqual(SPOTIFY_MODE_COMMAND_NAMES, ["bye", "lang", "logout", "model", "playlist", "quit", "queue", "random", "recommend"]);
assert.deepEqual(spotifyModeSlashCommands().map((command) => command.name), SPOTIFY_MODE_COMMAND_NAMES);
assert.deepEqual(spotifyModeSlashCommands("/").map((command) => command.name), SPOTIFY_MODE_COMMAND_NAMES);
assert.deepEqual(spotifyModeSlashCommands("/p").map((command) => command.name), ["playlist"]);
assert.deepEqual(spotifyModeSlashCommands("/sp").map((command) => command.name), []);

import assert from 'node:assert/strict';

import { SLASH_COMMANDS } from '../src/constants.js';
import {
    HELP_PANEL_VISIBLE_COMMANDS,
    helpPanelCommands,
    selectedHelpPanelCommand,
    visibleCommandWindow,
} from '../src/command-panel.js';
import {
    completeSlashCommand,
    matchingSlashCommand,
    slashCommandSuggestions,
    SPOTIFY_MODE_COMMAND_NAMES,
    spotifyModeSlashCommands,
    unknownSlashCommandMessage,
} from '../src/commands.js';

const allHelpCommands = helpPanelCommands(SLASH_COMMANDS);
const localizedHelpCommands = helpPanelCommands([
    {
        name: "help",
        usage: "/help",
        description: "显示命令列表",
    },
]);

assert.equal(HELP_PANEL_VISIBLE_COMMANDS, 8);
for (const command of SLASH_COMMANDS.filter((item) => item.enabled !== false)) {
    const words = command.description.trim().split(/\s+/);
    assert.equal(command.description[0], command.description[0]?.toLowerCase());
    assert.equal(command.description.endsWith("."), false);
    assert.ok(words.length >= 2 && words.length <= 5, `${command.name} shortcut description must contain 2-5 words`);
}
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
assert.equal(helpRecommend?.description, "recommend songs");
const slashRecommend = SLASH_COMMANDS.find((command) => command.name === "recommend");
assert.equal(slashRecommend?.needsArgument, false);
assert.equal(slashRecommend ? completeSlashCommand(slashRecommend) : null, "/recommend");

for (const hiddenName of ["pause", "volume", "progress", "stop"]) {
    assert.equal(SLASH_COMMANDS.find((command) => command.name === hiddenName), undefined);
    assert.equal(allHelpCommands.find((command) => command.name === hiddenName), undefined);
}

const helpPlayer = allHelpCommands.find((command) => command.name === "player");
const slashPlayer = SLASH_COMMANDS.find((command) => command.name === "player");
assert.equal(helpPlayer, undefined);
assert.equal(slashPlayer, undefined);
assert.equal(localizedHelpCommands.find((command) => command.name === "help")?.description, "显示命令列表");

const helpKeymap = allHelpCommands.find((command) => command.name === "keymap");
assert.equal(helpKeymap?.usage, "/keymap [on|off|toggle|status]");
assert.equal(helpKeymap?.description, "toggle playback shortcuts");

const slashLang = SLASH_COMMANDS.find((command) => command.name === "lang");
const helpLang = allHelpCommands.find((command) => command.name === "lang");
assert.equal(slashLang?.usage, "/lang");
assert.equal(slashLang?.enabled, false);
assert.equal(helpLang, undefined);
assert.deepEqual(slashCommandSuggestions("/lang"), []);
assert.equal(matchingSlashCommand("/lang"), undefined);
assert.equal(unknownSlashCommandMessage("/lang"), "Unknown command: /lang. Type /help to view available commands.");
assert.equal(unknownSlashCommandMessage("  /exp extra"), "Unknown command: /exp. Type /help to view available commands.");

const helpInfo = allHelpCommands.find((command) => command.name === "info");
assert.equal(helpInfo?.usage, "/info");
assert.equal(helpInfo?.description, "show runtime info");

const helpExit = allHelpCommands.find((command) => command.name === "exit");
assert.equal(helpExit?.usage, "/exit");
assert.equal(SLASH_COMMANDS.find((command) => command.name === "quit"), undefined);

const helpPlaylist = allHelpCommands.find((command) => command.name === "playlist");
assert.equal(helpPlaylist?.usage, "/playlist [name]|save [name]");
assert.equal(helpPlaylist?.description, "browse or save playlists");

const helpQueue = allHelpCommands.find((command) => command.name === "queue");
assert.equal(helpQueue?.usage, "/queue");
assert.equal(helpQueue?.description, "show playback queue");

assert.deepEqual(SPOTIFY_MODE_COMMAND_NAMES, ["bye", "extension", "exit", "info", "lang", "login", "logout", "memory", "model", "playlist", "queue", "random", "recommend", "settings", "spotify"]);
assert.deepEqual(spotifyModeSlashCommands().map((command) => command.name), SPOTIFY_MODE_COMMAND_NAMES.filter((name) => name !== "lang"));
assert.deepEqual(spotifyModeSlashCommands("/").map((command) => command.name), SPOTIFY_MODE_COMMAND_NAMES.filter((name) => name !== "lang"));
assert.deepEqual(spotifyModeSlashCommands("/p").map((command) => command.name), ["playlist"]);
assert.deepEqual(spotifyModeSlashCommands("/sp").map((command) => command.name), ["spotify"]);

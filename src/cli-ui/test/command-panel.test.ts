import assert from 'node:assert/strict';

import { SLASH_COMMANDS } from '../src/constants.js';
import {
    HELP_PANEL_VISIBLE_COMMANDS,
    helpPanelCommands,
    visibleCommandWindow,
} from '../src/command-panel.js';

/**
 * Defines the all help commands constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/command-panel.test.ts.
 */
const allHelpCommands = helpPanelCommands(SLASH_COMMANDS);

assert.equal(HELP_PANEL_VISIBLE_COMMANDS, 8);
assert.deepEqual(
    allHelpCommands.map((command) => command.name),
    [...allHelpCommands.map((command) => command.name)].sort(),
);

assert.equal(visibleCommandWindow(allHelpCommands, 0, HELP_PANEL_VISIBLE_COMMANDS).items.length, 8);
assert.equal(visibleCommandWindow(allHelpCommands, 0, HELP_PANEL_VISIBLE_COMMANDS).items[0]?.name, "bye");
assert.equal(visibleCommandWindow(allHelpCommands, 8, HELP_PANEL_VISIBLE_COMMANDS).items.at(-1)?.name, allHelpCommands[8]?.name);

/**
 * Defines the slash search constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/command-panel.test.ts.
 */
const slashSearch = SLASH_COMMANDS.find((command) => command.name === "search");
/**
 * Defines the help search constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/command-panel.test.ts.
 */
const helpSearch = allHelpCommands.find((command) => command.name === "search");
assert.equal(slashSearch?.description, "Search songs by keywords.");
assert.equal(helpSearch?.description, "Search songs by keywords.");

/**
 * Defines the help play constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/command-panel.test.ts.
 */
const helpPlay = allHelpCommands.find((command) => command.name === "play");
assert.equal(helpPlay?.usage, "/play <query/number>");
assert.equal(helpPlay?.description, "Play a song by query or result number.");

/**
 * Defines the help recommend constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/command-panel.test.ts.
 */
const helpRecommend = allHelpCommands.find((command) => command.name === "recommend");
assert.equal(helpRecommend?.description, "Recommend songs of preferred music taste.");

/**
 * Defines the help pause constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/command-panel.test.ts.
 */
const helpPause = allHelpCommands.find((command) => command.name === "pause");
assert.equal(helpPause?.usage, "/pause");
assert.equal(helpPause?.description, "Pause current playback");

/**
 * Defines the help volume constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/command-panel.test.ts.
 */
const helpVolume = allHelpCommands.find((command) => command.name === "volume");
assert.equal(helpVolume?.usage, "/volume <0-100>");
assert.equal(helpVolume?.description, "Set local playback volume");

/**
 * Defines the help player constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/command-panel.test.ts.
 */
const helpPlayer = allHelpCommands.find((command) => command.name === "player");
assert.equal(helpPlayer?.usage, "/player <auto|mpv|cvlc>");
assert.equal(helpPlayer?.description, "Set local playback backend");

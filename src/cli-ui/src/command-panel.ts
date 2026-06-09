import { SLASH_COMMANDS } from './constants.js';
import type { HelpCommand, SlashCommandSuggestion } from './types.js';

export const HELP_PANEL_VISIBLE_COMMANDS = 8;

export type CommandPanelCommand = Pick<SlashCommandSuggestion, "name" | "usage" | "description">;

/**
 * Coordinates the visible command window operation for the CLI UI runtime.
 *
 * @param commands Input value used by the visible command window operation.
 * @param selectedIndex Input value used by the visible command window operation.
 * @param visibleLimit Input value used by the visible command window operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function visibleCommandWindow<T>(
    commands: T[],
    selectedIndex: number,
    visibleLimit: number,
): { items: T[]; boundedIndex: number; startIndex: number } {
    if (commands.length === 0) {
        return { items: [], boundedIndex: 0, startIndex: 0 };
    }
    const boundedIndex = Math.min(Math.max(selectedIndex, 0), commands.length - 1);
    const limit = Math.min(Math.max(1, visibleLimit), commands.length);
    const maxStart = Math.max(0, commands.length - limit);
    const startIndex = Math.min(Math.max(0, boundedIndex - limit + 1), maxStart);
    return {
        items: commands.slice(startIndex, startIndex + limit),
        boundedIndex,
        startIndex,
    };
}

/**
 * Coordinates the help panel commands operation for the CLI UI runtime.
 *
 * @param commands Input value used by the help panel commands operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function helpPanelCommands(commands: HelpCommand[]): CommandPanelCommand[] {
    const conciseByName = new Map(SLASH_COMMANDS.map((command) => [command.name, command.description]));
    return [...commands]
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((command) => {
            const description = conciseByName.get(command.name) ?? command.description;
            return {
                name: command.name,
                usage: command.usage,
                description,
            };
        });
}

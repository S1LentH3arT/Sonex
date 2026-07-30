import { SLASH_COMMANDS } from './constants.js';
import { localizeSlashCommands } from './i18n.js';
import type { SlashCommandSuggestion, UiLanguage } from './types.js';

export const SPOTIFY_MODE_COMMAND_NAMES = ["apple", "bye", "connect", "exit", "info", "lang", "logout", "model", "playlist", "queue", "random", "recommend", "spotify"] as const;
export const APPLE_MODE_COMMAND_NAMES = ["apple", "bye", "connect", "exit", "info", "lang", "logout", "model", "queue", "spotify"] as const;

const SPOTIFY_MODE_COMMANDS = SPOTIFY_MODE_COMMAND_NAMES.map((name) => (
    SLASH_COMMANDS.find((command) => command.name === name)
)).filter((command): command is SlashCommandSuggestion => Boolean(command?.enabled !== false));
const APPLE_MODE_COMMANDS = APPLE_MODE_COMMAND_NAMES.map((name) => (
    SLASH_COMMANDS.find((command) => command.name === name)
)).filter((command): command is SlashCommandSuggestion => Boolean(command?.enabled !== false));

function commandSuggestionsFrom(commands: SlashCommandSuggestion[], input: string, language: UiLanguage): SlashCommandSuggestion[] {
    const trimmed = input.trimStart();
    if (!trimmed.startsWith("/")) return [];
    const token = trimmed.slice(1).split(/\s+/, 1)[0]?.toLowerCase() ?? "";
    return localizeSlashCommands(commands.filter(
        (command) => command.enabled !== false && command.name.startsWith(token),
    ), language);
}

/**
 * Coordinates the slash command suggestions operation for the CLI UI runtime.
 *
 * @param input Input value used by the slash command suggestions operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function slashCommandSuggestions(input: string, language: UiLanguage = "en"): SlashCommandSuggestion[] {
    return commandSuggestionsFrom(SLASH_COMMANDS, input, language);
}

export function spotifyModeSlashCommands(input: string = "/", language: UiLanguage = "en"): SlashCommandSuggestion[] {
    return commandSuggestionsFrom(SPOTIFY_MODE_COMMANDS, input, language);
}

export function appleModeSlashCommands(input: string = "/", language: UiLanguage = "en"): SlashCommandSuggestion[] {
    return commandSuggestionsFrom(APPLE_MODE_COMMANDS, input, language);
}

/**
 * Coordinates the slash command token operation for the CLI UI runtime.
 *
 * @param input Input value used by the slash command token operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function slashCommandToken(input: string): string {
    const trimmed = input.trimStart();
    if (!trimmed.startsWith("/")) return "";
    return trimmed.slice(1).split(/\s+/, 1)[0]?.toLowerCase() ?? "";
}

/**
 * Coordinates the matching slash command operation for the CLI UI runtime.
 *
 * @param input Input value used by the matching slash command operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function matchingSlashCommand(input: string): SlashCommandSuggestion | undefined {
    const token = slashCommandToken(input);
    return SLASH_COMMANDS.find(
        (command) => command.enabled !== false
            && (command.name === token || command.aliases?.includes(token)),
    );
}

/**
 * Coordinates the has slash command arguments operation for the CLI UI runtime.
 *
 * @param input Input value used by the has slash command arguments operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function hasSlashCommandArguments(input: string): boolean {
    const trimmed = input.trimStart();
    const spaceIndex = trimmed.indexOf(" ");
    return spaceIndex !== -1 && trimmed.slice(spaceIndex + 1).trim().length > 0;
}

/**
 * Coordinates the complete slash command operation for the CLI UI runtime.
 *
 * @param command Input value used by the complete slash command operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function completeSlashCommand(command: SlashCommandSuggestion): string {
    return command.needsArgument ? `/${command.name} ` : `/${command.name}`;
}

export function unknownSlashCommandMessage(input: string): string {
    const command = input.trimStart().split(/\s+/, 1)[0] || "/";
    return `Unknown command: ${command}. Type /help to view available commands.`;
}

import { SLASH_COMMANDS } from './constants.js';
import type { SlashCommandSuggestion } from './types.js';

/**
 * Coordinates the slash command suggestions operation for the CLI UI runtime.
 *
 * @param input Input value used by the slash command suggestions operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function slashCommandSuggestions(input: string): SlashCommandSuggestion[] {
    const trimmed = input.trimStart();
    if (!trimmed.startsWith("/")) return [];
    const token = trimmed.slice(1).split(/\s+/, 1)[0]?.toLowerCase() ?? "";
    return SLASH_COMMANDS.filter((command) => command.name.startsWith(token));
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
    return SLASH_COMMANDS.find((command) => command.name === token || command.aliases?.includes(token));
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

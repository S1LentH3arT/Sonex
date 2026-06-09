import { SLASH_COMMANDS } from './constants.js';
import type { SlashCommandSuggestion } from './types.js';

/**
 * Slash command suggestions.
 *
 * Coordinates the slash command suggestions operation for the CLI UI runtime.
 *
 * @param input Input value used by the slash command suggestions operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function slashCommandSuggestions(input: string): SlashCommandSuggestion[] {
    /**
     * Defines the trimmed constant.
     *
     * Stores stable configuration or display data consumed by commands.ts.
     */
    const trimmed = input.trimStart();
    if (!trimmed.startsWith("/")) return [];
    /**
     * Defines the token constant.
     *
     * Stores stable configuration or display data consumed by commands.ts.
     */
    const token = trimmed.slice(1).split(/\s+/, 1)[0]?.toLowerCase() ?? "";
    return SLASH_COMMANDS.filter((command) => command.name.startsWith(token));
}

/**
 * Slash command token.
 *
 * Coordinates the slash command token operation for the CLI UI runtime.
 *
 * @param input Input value used by the slash command token operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function slashCommandToken(input: string): string {
    /**
     * Defines the trimmed constant.
     *
     * Stores stable configuration or display data consumed by commands.ts.
     */
    const trimmed = input.trimStart();
    if (!trimmed.startsWith("/")) return "";
    return trimmed.slice(1).split(/\s+/, 1)[0]?.toLowerCase() ?? "";
}

/**
 * Matching slash command.
 *
 * Coordinates the matching slash command operation for the CLI UI runtime.
 *
 * @param input Input value used by the matching slash command operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function matchingSlashCommand(input: string): SlashCommandSuggestion | undefined {
    /**
     * Defines the token constant.
     *
     * Stores stable configuration or display data consumed by commands.ts.
     */
    const token = slashCommandToken(input);
    return SLASH_COMMANDS.find((command) => command.name === token || command.aliases?.includes(token));
}

/**
 * Has slash command arguments.
 *
 * Coordinates the has slash command arguments operation for the CLI UI runtime.
 *
 * @param input Input value used by the has slash command arguments operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function hasSlashCommandArguments(input: string): boolean {
    /**
     * Defines the trimmed constant.
     *
     * Stores stable configuration or display data consumed by commands.ts.
     */
    const trimmed = input.trimStart();
    /**
     * Defines the space index constant.
     *
     * Stores stable configuration or display data consumed by commands.ts.
     */
    const spaceIndex = trimmed.indexOf(" ");
    return spaceIndex !== -1 && trimmed.slice(spaceIndex + 1).trim().length > 0;
}

/**
 * Complete slash command.
 *
 * Coordinates the complete slash command operation for the CLI UI runtime.
 *
 * @param command Input value used by the complete slash command operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function completeSlashCommand(command: SlashCommandSuggestion): string {
    return command.needsArgument ? `/${command.name} ` : `/${command.name}`;
}

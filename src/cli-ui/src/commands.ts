import {SLASH_COMMANDS} from './constants.js';
import type {SlashCommandSuggestion} from './types.js';

export function slashCommandSuggestions(input: string): SlashCommandSuggestion[] {
    const trimmed = input.trimStart();
    if (!trimmed.startsWith("/")) return [];
    const token = trimmed.slice(1).split(/\s+/, 1)[0]?.toLowerCase() ?? "";
    return SLASH_COMMANDS.filter((command) => command.name.startsWith(token));
}

export function slashCommandToken(input: string): string {
    const trimmed = input.trimStart();
    if (!trimmed.startsWith("/")) return "";
    return trimmed.slice(1).split(/\s+/, 1)[0]?.toLowerCase() ?? "";
}

export function matchingSlashCommand(input: string): SlashCommandSuggestion | undefined {
    const token = slashCommandToken(input);
    return SLASH_COMMANDS.find((command) => command.name === token || command.aliases?.includes(token));
}

export function hasSlashCommandArguments(input: string): boolean {
    const trimmed = input.trimStart();
    const spaceIndex = trimmed.indexOf(" ");
    return spaceIndex !== -1 && trimmed.slice(spaceIndex + 1).trim().length > 0;
}

export function completeSlashCommand(command: SlashCommandSuggestion): string {
    return command.needsArgument ? `/${command.name} ` : `/${command.name}`;
}

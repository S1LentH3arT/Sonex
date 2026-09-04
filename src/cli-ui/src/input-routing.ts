import { hasSlashCommandArguments, matchingSlashCommand } from './commands.js';
import { resolveConfirmDecisionFromInput, resolveConfirmInputDecision } from './confirm-choice.js';
import type { ConfirmChoice, ConfirmState, SlashCommandSuggestion } from './types.js';

export type InputRoute =
    | { type: 'empty' }
    | { type: 'ignore' }
    | { type: 'confirm'; decision: string }
    | { type: 'extension_input'; value: string }
    | { type: 'safe_exit'; reason: string }
    | { type: 'info' }
    | { type: 'slash_completion'; command: SlashCommandSuggestion }
    | { type: 'unknown_slash'; value: string }
    | { type: 'setup_input'; channel: 'spotify' | 'auth'; value: string }
    | { type: 'user_input'; value: string; command?: SlashCommandSuggestion };

export type InputRoutingContext = {
    confirm: ConfirmState;
    selectedConfirmChoice: ConfirmChoice | null;
    selectableConfirmChoices: ConfirmChoice[];
    extensionPanelActive: boolean;
    extensionInputFocused: boolean;
    extensionSetupInput: { placeholder: string; mask?: boolean } | null;
    authSetupActive: boolean;
    spotifySetupActive: boolean;
    selectedSlashCommand: SlashCommandSuggestion | undefined;
};

export function resolveInputRoute(value: string, context: InputRoutingContext): InputRoute {
    const text = value.trim();
    if (!text) return { type: 'empty' };

    if (context.confirm) {
        const inputDecision = resolveConfirmInputDecision(text, context.selectedConfirmChoice);
        if (inputDecision) return { type: 'confirm', decision: inputDecision };
        const decision = resolveConfirmDecisionFromInput(text, context.selectableConfirmChoices);
        return decision ? { type: 'confirm', decision } : { type: 'ignore' };
    }

    if (context.extensionPanelActive) {
        return context.extensionInputFocused
            && context.extensionSetupInput
            ? { type: 'extension_input', value: text }
            : { type: 'ignore' };
    }

    const command = matchingSlashCommand(text);
    if (!context.authSetupActive && !context.spotifySetupActive) {
        if (command?.name === 'bye' || command?.name === 'exit') {
            return { type: 'safe_exit', reason: command.name };
        }
        if (command?.name === 'info') return { type: 'info' };
        if (text.startsWith('/') && !command) {
            return context.selectedSlashCommand
                ? { type: 'slash_completion', command: context.selectedSlashCommand }
                : { type: 'unknown_slash', value: text };
        }
        if (command?.needsArgument && !hasSlashCommandArguments(text)) {
            return { type: 'slash_completion', command };
        }
    }

    if (context.spotifySetupActive) return { type: 'setup_input', channel: 'spotify', value: text };
    if (context.authSetupActive) return { type: 'setup_input', channel: 'auth', value: text };
    return { type: 'user_input', value: text, command };
}

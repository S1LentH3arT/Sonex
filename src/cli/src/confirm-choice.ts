import type { ConfirmChoice } from './types.js';

const normalize = (value: string): string => value
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_-]+/gu, '');

export function isCancelConfirmChoice(choice: ConfirmChoice): boolean {
    const value = normalize(choice.value);
    const label = normalize(choice.label);
    return value === 'cancel'
        || value === 'deny'
        || label === 'cancel'
        || label === 'no'
        || label === '取消';
}

export function getVisibleConfirmChoices(
    choices: ConfirmChoice[],
    includeCancel = false,
): ConfirmChoice[] {
    return includeCancel
        ? choices
        : choices.filter((choice) => !isCancelConfirmChoice(choice));
}

export function getSelectableConfirmChoices(
    choices: ConfirmChoice[],
    includeCancel = false,
): ConfirmChoice[] {
    return getVisibleConfirmChoices(choices, includeCancel).filter((choice) => !choice.disabled);
}

export function resolveConfirmChoiceDisplayIndex(
    choices: ConfirmChoice[],
    selectableIndex: number,
    includeCancel = false,
): number {
    const visibleChoices = getVisibleConfirmChoices(choices, includeCancel);
    const selectableChoices = getSelectableConfirmChoices(choices, includeCancel);
    const selectedChoice = selectableChoices[
        Math.min(Math.max(selectableIndex, 0), Math.max(0, selectableChoices.length - 1))
    ];
    if (!selectedChoice) return -1;
    return Math.max(0, visibleChoices.findIndex((choice) => choice.value === selectedChoice.value));
}

/**
 * Coordinates the resolve confirm decision from input operation for the CLI UI runtime.
 *
 * @param input Input value used by the resolve confirm decision from input operation.
 * @param choices Input value used by the resolve confirm decision from input operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function resolveConfirmDecisionFromInput(input: string, choices: ConfirmChoice[]): string | null {
    const selectableChoices = getSelectableConfirmChoices(choices);
    const normalized = normalize(input);
    if (!normalized) return null;

    const numeric = Number.parseInt(normalized, 10);
    if (Number.isInteger(numeric) && String(numeric) === normalized) {
        return selectableChoices[numeric - 1]?.value ?? null;
    }

    for (const choice of selectableChoices) {
        if (normalize(choice.value) === normalized || normalize(choice.label) === normalized) {
            return choice.value;
        }
    }

    return null;
}

/**
 * Coordinates the resolve confirm input decision operation for the CLI UI runtime.
 *
 * @param input Input value used by the resolve confirm input decision operation.
 * @param choice Input value used by the resolve confirm input decision operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function resolveConfirmInputDecision(input: string, choice: ConfirmChoice | null): string | null {
    const text = input.trim();
    if (!text || !choice?.input) return null;
    return `${choice.value}:${encodeURIComponent(text)}`;
}

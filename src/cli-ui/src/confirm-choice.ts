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

export function getVisibleConfirmChoices(choices: ConfirmChoice[]): ConfirmChoice[] {
    return choices.filter((choice) => !isCancelConfirmChoice(choice));
}

/**
 * Coordinates the resolve confirm decision from input operation for the CLI UI runtime.
 *
 * @param input Input value used by the resolve confirm decision from input operation.
 * @param choices Input value used by the resolve confirm decision from input operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function resolveConfirmDecisionFromInput(input: string, choices: ConfirmChoice[]): string | null {
    const visibleChoices = getVisibleConfirmChoices(choices);
    const normalized = normalize(input);
    if (!normalized) return null;

    const numeric = Number.parseInt(normalized, 10);
    if (Number.isInteger(numeric) && String(numeric) === normalized) {
        return visibleChoices[numeric - 1]?.value ?? null;
    }

    for (const choice of visibleChoices) {
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

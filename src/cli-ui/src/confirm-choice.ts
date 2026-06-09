import type { ConfirmChoice } from './types.js';

/**
 * Defines the normalize function.
 *
 * Implements the normalize behavior used by confirm-choice.ts.
 *
 * @param value Input value used by the normalize operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const normalize = (value: string): string => value
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_-]+/gu, '');

/**
 * Resolve confirm decision from input.
 *
 * Coordinates the resolve confirm decision from input operation for the CLI UI runtime.
 *
 * @param input Input value used by the resolve confirm decision from input operation.
 * @param choices Input value used by the resolve confirm decision from input operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function resolveConfirmDecisionFromInput(input: string, choices: ConfirmChoice[]): string | null {
    /**
     * Defines the normalized constant.
     *
     * Stores stable configuration or display data consumed by confirm-choice.ts.
     */
    const normalized = normalize(input);
    if (!normalized) return null;

    /**
     * Defines the numeric constant.
     *
     * Stores stable configuration or display data consumed by confirm-choice.ts.
     */
    const numeric = Number.parseInt(normalized, 10);
    if (Number.isInteger(numeric) && String(numeric) === normalized) {
        return choices[numeric - 1]?.value ?? null;
    }

    for (const choice of choices) {
        if (normalize(choice.value) === normalized || normalize(choice.label) === normalized) {
            return choice.value;
        }
    }

    return null;
}

/**
 * Resolve confirm input decision.
 *
 * Coordinates the resolve confirm input decision operation for the CLI UI runtime.
 *
 * @param input Input value used by the resolve confirm input decision operation.
 * @param choice Input value used by the resolve confirm input decision operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function resolveConfirmInputDecision(input: string, choice: ConfirmChoice | null): string | null {
    /**
     * Defines the text constant.
     *
     * Stores stable configuration or display data consumed by confirm-choice.ts.
     */
    const text = input.trim();
    if (!text || !choice?.input) return null;
    return `${choice.value}:${encodeURIComponent(text)}`;
}

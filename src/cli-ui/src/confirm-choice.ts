import type {ConfirmChoice} from './types.js';

const normalize = (value: string): string => value
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_-]+/gu, '');

export function resolveConfirmDecisionFromInput(input: string, choices: ConfirmChoice[]): string | null {
    const normalized = normalize(input);
    if (!normalized) return null;

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

export function resolveConfirmInputDecision(input: string, choice: ConfirmChoice | null): string | null {
    const text = input.trim();
    if (!text || !choice?.input) return null;
    return `${choice.value}:${encodeURIComponent(text)}`;
}

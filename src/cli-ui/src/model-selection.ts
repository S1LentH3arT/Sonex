import stringWidth from 'string-width';

import type { AuthMethodChoice } from './types.js';

export const modelPanelLabelWidth = (choices: AuthMethodChoice[]): number => (
    Math.max(0, ...choices.map((choice) => stringWidth(choice.label))) + 1
);

export const formatModelPanelLabel = (choice: AuthMethodChoice, width: number): string => {
    const label = choice.label;
    const labelWidth = stringWidth(label);
    if (labelWidth >= width) return label;
    return `${label}${" ".repeat(width - labelWidth)}`;
};

export const filterModelChoices = (
    choices: AuthMethodChoice[],
    query: string,
): AuthMethodChoice[] => {
    const tokens = query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
    if (tokens.length === 0) return choices;
    return choices.filter((choice) => {
        const searchable = [choice.value, choice.label, choice.provider ?? '']
            .join(' ')
            .toLocaleLowerCase();
        return tokens.every((token) => searchable.includes(token));
    });
};

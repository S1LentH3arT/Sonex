import type { AuthMethodChoice } from './types.js';

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

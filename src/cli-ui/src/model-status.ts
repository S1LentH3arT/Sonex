export type ModelStatusInput = {
    ready: boolean;
    provider: string;
    model: string;
    model_label?: string | null;
};

const PROVIDER_BRANDS: Readonly<Record<string, string>> = {
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    gemini: 'Google Gemini',
    deepseek: 'DeepSeek',
    openrouter: 'OpenRouter',
    zai: 'Z.AI',
    kimi_global: 'Kimi Global',
    kimi_cn: 'Kimi CN',
    minimax_global: 'MiniMax Global',
    minimax_cn: 'MiniMax CN',
    xai: 'xAI',
    custom: 'Custom',
};

export const formatModelStatus = (
    input: ModelStatusInput,
): string | null => {
    if (!input.ready) return null;

    const provider = input.provider.trim();
    const model = (input.model_label || input.model).trim();
    if (!provider || !model) return null;

    const normalizedProvider = provider.toLowerCase();
    const providerLabel = normalizedProvider.startsWith('custom__')
        ? 'Custom'
        : PROVIDER_BRANDS[normalizedProvider] ?? provider;
    return `[${providerLabel}] ${model}`;
};

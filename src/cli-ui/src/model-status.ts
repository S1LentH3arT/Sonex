export type ModelStatusInput = {
    ready: boolean;
    provider: string;
    model: string;
};

const PROVIDER_BRANDS: Readonly<Record<string, string>> = {
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    gemini: 'Gemini',
    deepseek: 'DeepSeek',
    ollama: 'Ollama',
};

export const formatModelStatus = (
    input: ModelStatusInput,
): string | null => {
    if (!input.ready) return null;

    const provider = input.provider.trim();
    const model = input.model.trim();
    if (!provider || !model) return null;

    const providerLabel = PROVIDER_BRANDS[provider.toLowerCase()] ?? provider;
    return `[${providerLabel}] ${model}`;
};

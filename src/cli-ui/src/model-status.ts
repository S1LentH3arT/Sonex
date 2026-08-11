import type { SessionTokenUsage } from './types.js';

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

export const formatTokenCount = (value: number): string => {
    const tokens = Math.max(0, Math.floor(value));
    return tokens > 1_000 ? `${Math.floor(tokens / 1_000)}k` : String(tokens);
};

export const formatModelStatus = (
    input: ModelStatusInput,
    tokenUsage: SessionTokenUsage,
): string | null => {
    if (!input.ready) return null;

    const provider = input.provider.trim();
    const model = (input.model_label || input.model).trim();
    if (!provider || !model) return null;

    const normalizedProvider = provider.toLowerCase();
    const providerLabel = normalizedProvider.startsWith('custom__')
        ? 'Custom'
        : PROVIDER_BRANDS[normalizedProvider] ?? provider;
    const modelLabel = `[${providerLabel}] ${model}`;
    if (tokenUsage.inputTokens <= 0 && tokenUsage.outputTokens <= 0) return modelLabel;
    return `↑${formatTokenCount(tokenUsage.inputTokens)} ↓${formatTokenCount(tokenUsage.outputTokens)} ${modelLabel}`;
};

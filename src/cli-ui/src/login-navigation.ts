import type { AuthMethodChoice } from './types.js';

export function resolveLoginProviderSelectionIndex(
    providers: AuthMethodChoice[],
    currentProvider: string,
): number {
    const providerIndex = providers.findIndex((choice) => choice.value === currentProvider);
    if (providerIndex >= 0) return providerIndex;
    const activeIndex = providers.findIndex((choice) => choice.connection_status === 'active');
    return activeIndex >= 0 ? activeIndex : 0;
}

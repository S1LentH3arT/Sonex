export type PanelName = 'track' | 'memory' | 'extension' | 'help' | 'language';

export type PanelLifecycleTrigger = 'input' | 'info' | 'extension_event' | 'help_event' | 'setup_event' | 'safe_exit' | 'bye';

export type PanelLifecyclePlan = Readonly<{
    close: readonly PanelName[];
    resetSelection: readonly PanelName[];
}>;

const plan = (close: readonly PanelName[], resetSelection: readonly PanelName[] = []): PanelLifecyclePlan => ({ close, resetSelection });

export function planPanelLifecycle(trigger: PanelLifecycleTrigger): PanelLifecyclePlan {
    switch (trigger) {
        case 'input':
        case 'info':
        case 'safe_exit':
            return plan(['help', 'track', 'language'], ['help', 'track']);
        case 'extension_event':
            return plan(['track', 'memory', 'help', 'language']);
        case 'help_event':
            return plan(['track', 'language'], ['help']);
        case 'setup_event':
            return plan(['help'], ['help']);
        case 'bye':
            return plan(['help', 'track'], ['help', 'track']);
    }
}

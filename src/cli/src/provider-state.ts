import type { AuthSetupState, ProviderModeState, ServerEvent, SpotifyModeState, SpotifySetupState } from './types.js';

type ProviderEvent = Extract<ServerEvent, {
    type: 'spotify_mode' | 'provider_mode' | 'spotify_setup' | 'auth_setup';
}>;

export type ProviderState = Readonly<{
    spotifyMode: SpotifyModeState;
    providerMode: ProviderModeState;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
}>;

export type ProviderAction =
    | { type: 'event'; event: ProviderEvent }
    | { type: 'clear_spotify_setup' }
    | { type: 'clear_auth_setup' }
    | { type: 'replace'; state: ProviderState };

export const initialProviderState: ProviderState = {
    spotifyMode: { enabled: false },
    providerMode: { provider: 'normal', enabled: false },
    spotifySetup: null,
    authSetup: null,
};

export function reduceProviderState(state: ProviderState, action: ProviderAction): ProviderState {
    if (action.type === 'replace') return action.state;
    if (action.type === 'clear_spotify_setup') return { ...state, spotifySetup: null };
    if (action.type === 'clear_auth_setup') return { ...state, authSetup: null };

    const event = action.event;
    switch (event.type) {
        case 'spotify_mode':
            return {
                ...state,
                spotifyMode: {
                    enabled: event.enabled,
                    device_id: event.device_id,
                    device_name: event.device_name,
                },
            };
        case 'provider_mode':
            return {
                ...state,
                providerMode: {
                    provider: event.provider,
                    enabled: event.enabled,
                    connection_status: event.connection_status,
                },
            };
        case 'spotify_setup':
            return {
                ...state,
                spotifySetup: {
                    step: event.step,
                    title: event.title,
                    message: event.message,
                    prompt: event.prompt,
                    mask: event.mask,
                    active: event.active !== false,
                },
            };
        case 'auth_setup':
            return {
                ...state,
                authSetup: event.active === false && event.step === 'model'
                    ? null
                    : {
                        provider: event.provider,
                        step: event.step,
                        title: event.title,
                        message: event.message,
                        prompt: event.prompt,
                        placeholder: event.placeholder,
                        help_text: event.help_text,
                        mask: event.mask,
                        active: event.active !== false,
                        methods: event.methods,
                        providers: event.providers,
                        models: event.models,
                    },
            };
    }
}

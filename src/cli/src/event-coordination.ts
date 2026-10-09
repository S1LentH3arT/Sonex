import type { PanelLifecycleTrigger } from './panel-lifecycle.js';
import type { ShellRegion } from './layout.js';
import { reduceShellState, type ShellState } from './shell-state.js';
import type { PlayerState, ServerEvent, UiLanguage } from './types.js';

export type ServerEventCoordination = Readonly<{
    region?: ShellRegion;
    panelLifecycle?: PanelLifecycleTrigger;
    shellState?: ShellState;
}>;

export type ServerEventCoordinationContext = Readonly<{
    shellState?: ShellState;
    providerMode?: 'spotify' | null;
}>;

export type ServerEventCoordinationBindings = Readonly<{
    shellState: () => ShellState;
    providerMode: () => 'spotify' | null;
    isConfirmDismissed: (id: string) => boolean;
    applyRuntimeEvent: (event: ServerEvent, rawEvent: ServerEvent) => void;
    applyProviderEvent: (
        event: Extract<ServerEvent, { type: 'spotify_mode' | 'provider_mode' | 'spotify_setup' | 'auth_setup' }>,
    ) => void;
    dispatchServerEvent: (event: ServerEvent, language: UiLanguage, dismissedConfirm: boolean) => void;
    applyPanelLifecycle: (trigger: PanelLifecycleTrigger) => void;
    switchRegion: (region: ShellRegion) => void;
    applyShellState: (state: ShellState) => void;
    clearInput: () => void;
    resetRecommendationInput: () => void;
    resetLaunchPreparingFrame: () => void;
    dismissConfirm: (id: string) => void;
    captureAuthState: (event: Extract<ServerEvent, { type: 'auth_state' }>) => void;
    exit: () => void;
}>;

function playerShellState(event: PlayerState, context: ServerEventCoordinationContext): ShellState | undefined {
    if (!context.shellState) return undefined;
    return reduceShellState(context.shellState, {
        type: 'player_event',
        player: event,
        spotifyModeEnabled: false,
        providerMode: context.providerMode,
    });
}

export function planServerEventCoordination(
    event: ServerEvent,
    context: ServerEventCoordinationContext = {},
): ServerEventCoordination {
    switch (event.type) {
        case 'track_panel':
            return { region: 'trackPanel' };
        case 'memory_panel':
            return { region: 'memoryPanel' };
        case 'extension_panel':
            return { panelLifecycle: 'extension_event' };
        case 'confirm':
            return { region: 'chat' };
        case 'player': {
            const shellState = playerShellState(event.state, context);
            return shellState ? { shellState, region: shellState.region } : {};
        }
        case 'spotify_mode':
            if (!event.enabled && context.shellState?.region === 'spotifyImmersive') {
                const shellState = reduceShellState(context.shellState, { type: 'set_region', region: 'chat' });
                return { shellState, region: 'chat' };
            }
            return {};
        case 'provider_mode':
            if (!event.enabled && context.shellState?.region === 'providerImmersive') {
                const shellState = reduceShellState(context.shellState, { type: 'set_region', region: 'chat' });
                return { shellState, region: 'chat' };
            }
            return {};
        case 'spotify_setup':
            return event.active === false ? { panelLifecycle: 'setup_event' } : { region: 'chat', panelLifecycle: 'setup_event' };
        case 'auth_setup':
            return event.active === false ? { panelLifecycle: 'setup_event' } : { region: 'chat', panelLifecycle: 'setup_event' };
        case 'help_panel':
            return { region: 'chat', panelLifecycle: 'help_event' };
        case 'bye':
            return { region: 'chat', panelLifecycle: 'bye' };
        default:
            return {};
    }
}

export function applyServerEventCoordination(
    event: ServerEvent,
    rawEvent: ServerEvent,
    language: UiLanguage,
    bindings: ServerEventCoordinationBindings,
): void {
    if (event.type === 'chat' || event.type === 'error' || event.type === 'proxy_state') return;

    bindings.applyRuntimeEvent(event, rawEvent);
    if (event.type === 'spotify_mode' || event.type === 'provider_mode' || event.type === 'spotify_setup' || event.type === 'auth_setup') {
        bindings.applyProviderEvent(event);
    }

    const shellState = bindings.shellState();
    const coordination = planServerEventCoordination(event, {
        shellState,
        providerMode: bindings.providerMode(),
    });
    const dismissedConfirm = event.type === 'confirm' && bindings.isConfirmDismissed(event.id);
    bindings.dispatchServerEvent(event, language, dismissedConfirm);
    if (!dismissedConfirm && coordination.panelLifecycle) {
        bindings.applyPanelLifecycle(coordination.panelLifecycle);
    }

    switch (event.type) {
        case 'activity':
            bindings.resetLaunchPreparingFrame();
            break;
        case 'input_state':
            if (event.disabled && event.reason === 'recommendation') {
                bindings.resetRecommendationInput();
            }
            break;
        case 'track_panel':
        case 'memory_panel':
        case 'confirm':
        case 'spotify_setup':
        case 'auth_setup':
        case 'help_panel':
        case 'bye':
            if (event.type === 'confirm' && dismissedConfirm) break;
            if (event.type === 'auth_setup' && event.active === false && event.step === 'model') {
                bindings.clearInput();
                break;
            }
            if (event.type === 'confirm' || (event.type === 'auth_setup' && event.step === 'model')) {
                bindings.clearInput();
            }
            if (coordination.region) {
                bindings.switchRegion(coordination.region);
            }
            if (event.type === 'bye') bindings.exit();
            break;
        case 'player':
            if (coordination.shellState) {
                if (coordination.shellState.region !== shellState.region) {
                    bindings.switchRegion(coordination.shellState.region);
                }
                bindings.applyShellState(coordination.shellState);
            }
            break;
        case 'spotify_mode':
        case 'provider_mode':
            if (coordination.shellState) {
                bindings.switchRegion(coordination.shellState.region);
                bindings.applyShellState(coordination.shellState);
            }
            break;
        case 'confirm_dismiss':
            bindings.dismissConfirm(event.id);
            break;
        case 'auth_state':
            bindings.captureAuthState(event);
            break;
        default:
            break;
    }
}

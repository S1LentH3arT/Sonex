import type { ServerEvent } from './types.js';
import type { PanelLifecycleTrigger } from './panel-lifecycle.js';
import type { ShellRegion } from './layout.js';
import { reduceShellState, type ShellState } from './shell-state.js';
import type { PlayerState } from './types.js';

export type ServerEventCoordination = Readonly<{
    region?: ShellRegion;
    panelLifecycle?: PanelLifecycleTrigger;
    shellState?: ShellState;
}>;

export type ServerEventCoordinationContext = Readonly<{
    shellState?: ShellState;
    providerMode?: 'spotify' | null;
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

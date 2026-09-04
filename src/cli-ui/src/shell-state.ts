import type { PlayerState } from './types.js';
import { resolveRegionAfterPlayerEvent, toggleShellRegion, type ShellRegion } from './layout.js';
import type { TerminalSurface } from './terminal-surface.js';

export type ShellState = {
    region: ShellRegion;
    playbackSessionActive: boolean;
};

export const initialShellState: ShellState = {
    region: 'chat',
    playbackSessionActive: false,
};

export function surfaceForShellRegion(region: ShellRegion): TerminalSurface {
    return region === 'chat' || region === 'memoryPanel' ? 'main' : 'alternate';
}

export type ShellSurfaceTransition = Readonly<{
    changed: boolean;
    target: TerminalSurface;
}>;

export function planShellSurfaceTransition(currentRegion: ShellRegion, nextRegion: ShellRegion): ShellSurfaceTransition {
    return {
        changed: currentRegion !== nextRegion,
        target: surfaceForShellRegion(nextRegion),
    };
}

export type ShellStateAction =
    | { type: 'replace'; state: ShellState }
    | { type: 'set_region'; region: ShellRegion }
    | { type: 'player_event'; player: PlayerState; spotifyModeEnabled?: boolean; providerMode?: 'spotify' | null }
    | { type: 'toggle_region'; spotifyModeEnabled?: boolean; providerModeEnabled?: boolean };

export function reduceShellState(state: ShellState, action: ShellStateAction): ShellState {
    if (action.type === 'replace') return action.state;
    if (action.type === 'set_region') return { ...state, region: action.region };
    if (action.type === 'player_event') {
        const transition = resolveRegionAfterPlayerEvent({
            currentRegion: state.region,
            wasSessionActive: state.playbackSessionActive,
            player: action.player,
            spotifyModeEnabled: action.spotifyModeEnabled,
            providerMode: action.providerMode,
        });
        return {
            region: transition.region,
            playbackSessionActive: transition.sessionActive,
        };
    }
    return {
        ...state,
        region: toggleShellRegion(
            state.region,
            state.playbackSessionActive,
            action.spotifyModeEnabled,
            action.providerModeEnabled,
        ),
    };
}

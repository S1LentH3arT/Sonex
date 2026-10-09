import assert from 'node:assert/strict';
import test from 'node:test';
import { applyServerEventCoordination, planServerEventCoordination, type ServerEventCoordinationBindings } from '../src/event-coordination.js';
import type { ShellRegion } from '../src/layout.js';
import type { PanelLifecycleTrigger } from '../src/panel-lifecycle.js';
import type { ShellState } from '../src/shell-state.js';

test('panel events coordinate region and lifecycle through one seam', () => {
    assert.deepEqual(
        planServerEventCoordination({ type: 'track_panel', panel: 'queue', title: 'Queue', tracks: [] }),
        { region: 'trackPanel' },
    );
    assert.deepEqual(
        planServerEventCoordination({ type: 'extension_panel', view: 'list', title: 'Extensions', extensions: [] }),
        { panelLifecycle: 'extension_event' },
    );
    assert.deepEqual(
        planServerEventCoordination({ type: 'help_panel', title: 'Help', hint: 'Esc', commands: [] }),
        { region: 'chat', panelLifecycle: 'help_event' },
    );
});

test('inactive setup events close owned panels without forcing a region switch', () => {
    assert.deepEqual(
        planServerEventCoordination({
            type: 'auth_setup',
            provider: 'openai',
            step: 'model',
            title: 'Done',
            message: 'Done',
            active: false,
        }),
        { panelLifecycle: 'setup_event' },
    );
});

test('player coordination owns the shell transition calculation', () => {
    const coordination = planServerEventCoordination(
        {
            type: 'player',
            state: { name: 'Song', artist: 'Artist', album: 'Album', duration_ms: 1, progress_ms: 0, is_playing: true },
        },
        { shellState: { region: 'chat', playbackSessionActive: false } },
    );
    assert.deepEqual(coordination.shellState, { region: 'miniPlayer', playbackSessionActive: true });
    assert.equal(coordination.region, 'miniPlayer');
});

test('applies state, provider, panel, shell, and input effects in order', () => {
    const calls: string[] = [];
    let shellState: ShellState = { region: 'chat', playbackSessionActive: false };
    const bindings: ServerEventCoordinationBindings = {
        shellState: () => shellState,
        providerMode: () => null,
        isConfirmDismissed: () => false,
        applyRuntimeEvent: () => calls.push('runtime'),
        applyProviderEvent: () => calls.push('provider'),
        dispatchServerEvent: () => calls.push('server'),
        applyPanelLifecycle: (trigger: PanelLifecycleTrigger) => calls.push(`panel:${trigger}`),
        switchRegion: (region: ShellRegion) => {
            calls.push(`region:${region}`);
            shellState = { ...shellState, region };
        },
        applyShellState: (state: typeof shellState) => {
            calls.push('shell');
            shellState = state;
        },
        clearInput: () => calls.push('clear-input'),
        resetRecommendationInput: () => calls.push('reset-recommendation-input'),
        resetLaunchPreparingFrame: () => calls.push('reset-launch-frame'),
        dismissConfirm: () => calls.push('dismiss-confirm'),
        captureAuthState: () => calls.push('capture-auth'),
        exit: () => calls.push('exit'),
    };

    applyServerEventCoordination(
        { type: 'player', state: { name: 'Song', artist: 'Artist', album: 'Album', duration_ms: 1, progress_ms: 0, is_playing: true } },
        { type: 'player', state: { name: 'Song', artist: 'Artist', album: 'Album', duration_ms: 1, progress_ms: 0, is_playing: true } },
        'en',
        bindings,
    );
    assert.deepEqual(calls, ['runtime', 'server', 'region:miniPlayer', 'shell']);
    assert.deepEqual(shellState, { region: 'miniPlayer', playbackSessionActive: true });

    calls.length = 0;
    applyServerEventCoordination(
        { type: 'auth_setup', provider: 'openai', step: 'model', title: 'Done', message: 'Done', active: false },
        { type: 'auth_setup', provider: 'openai', step: 'model', title: 'Done', message: 'Done', active: false },
        'en',
        bindings,
    );
    assert.deepEqual(calls, ['runtime', 'provider', 'server', 'panel:setup_event', 'clear-input']);
});

test('dismissed confirms update state without clearing input or switching region', () => {
    const calls: string[] = [];
    applyServerEventCoordination(
        { type: 'confirm', id: 'confirm-1', tool_name: 'play', tool_args: {} },
        { type: 'confirm', id: 'confirm-1', tool_name: 'play', tool_args: {} },
        'en',
        {
            shellState: () => ({ region: 'trackPanel', playbackSessionActive: false }),
            providerMode: () => null,
            isConfirmDismissed: () => true,
            applyRuntimeEvent: () => calls.push('runtime'),
            applyProviderEvent: () => calls.push('provider'),
            dispatchServerEvent: (_event, _language, dismissed) => calls.push(`server:${dismissed}`),
            applyPanelLifecycle: () => calls.push('panel'),
            switchRegion: () => calls.push('region'),
            applyShellState: () => calls.push('shell'),
            clearInput: () => calls.push('clear-input'),
            resetRecommendationInput: () => calls.push('reset-recommendation-input'),
            resetLaunchPreparingFrame: () => calls.push('reset-launch-frame'),
            dismissConfirm: () => calls.push('dismiss-confirm'),
            captureAuthState: () => calls.push('capture-auth'),
            exit: () => calls.push('exit'),
        },
    );
    assert.deepEqual(calls, ['runtime', 'server:true']);
});

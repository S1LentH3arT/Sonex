import { DEFAULT_CONFIRM_CHOICES, FALLBACK_MODEL_NAME } from './constants.js';
import { helpCommandsForLanguage } from './i18n.js';
import { resolveLoginProviderSelectionIndex } from './login-navigation.js';
import { markQueuedTracks } from './track-panel.js';
import type {
    AuthRuntimeState,
    ConfirmState,
    CoverImageEvent,
    CoverPatternEvent,
    ExtensionPanelState,
    HelpPanelState,
    MemoryPanelState,
    PlayerState,
    ServerEvent,
    TrackPanelState,
    TrackPanelTrack,
    TrackSummary,
    UiLanguage,
} from './types.js';

export type MemoryEditorState = {
    mode: 'search' | 'add' | 'edit' | 'setting';
    value: string;
    settingKey?: string;
} | null;

export type ServerEventState = {
    queueItems: TrackPanelTrack[];
    searchItems: TrackSummary[];
    trackPanel: TrackPanelState;
    memoryPanel: MemoryPanelState;
    extensionPanel: ExtensionPanelState;
    extensionPanelIndex: number;
    extensionInputFocused: boolean;
    memorySearchQuery: string;
    memoryEditor: MemoryEditorState;
    player: PlayerState;
    coverUrl: string | null;
    coverImage: CoverImageEvent | null;
    coverPattern: CoverPatternEvent | null;
    confirm: ConfirmState;
    confirmIndex: number;
    authState: AuthRuntimeState;
    helpPanel: HelpPanelState;
    helpPanelIndex: number;
    trackPanelIndex: number;
    memoryPanelIndex: number;
    loginSelectionIndex: number;
    isExiting: boolean;
};

export const initialServerEventState: ServerEventState = {
    queueItems: [],
    searchItems: [],
    trackPanel: null,
    memoryPanel: null,
    extensionPanel: null,
    extensionPanelIndex: 0,
    extensionInputFocused: false,
    memorySearchQuery: '',
    memoryEditor: null,
    player: { name: '-', artist: '-', album: '-', duration_ms: 0, progress_ms: 0, is_playing: false },
    coverUrl: null,
    coverImage: null,
    coverPattern: null,
    confirm: null,
    confirmIndex: 0,
    authState: {
        ready: false,
        provider: 'openai',
        model: FALLBACK_MODEL_NAME,
        auth_type: 'none',
        credential_source: 'pending',
    },
    helpPanel: null,
    helpPanelIndex: 0,
    trackPanelIndex: 0,
    memoryPanelIndex: 0,
    loginSelectionIndex: 0,
    isExiting: false,
};

type PatchAction = {
    type: 'patch';
    key: keyof ServerEventState;
    value: unknown;
};

export type ServerEventStateAction =
    | { type: 'event'; event: ServerEvent; language: UiLanguage; dismissedConfirm?: boolean }
    | PatchAction;

function extensionIndex(event: Extract<ServerEvent, { type: 'extension_panel' }>): number {
    if (event.view === 'detail') {
        const actions = event.detail?.actions ?? [];
        const focusedIndex = event.detail?.selected_action ? actions.indexOf(event.detail.selected_action) : 0;
        return focusedIndex >= 0 ? focusedIndex : 0;
    }
    if (event.view === 'setup') {
        return event.setup?.dependencies && event.setup.selected_dependency
            ? Math.max(0, event.setup.dependencies.findIndex((dependency) => dependency.id === event.setup?.selected_dependency))
            : 0;
    }
    return event.selected_extension
        ? Math.max(0, event.extensions.findIndex((extension) => extension.id === event.selected_extension))
        : 0;
}

function reduceEvent(state: ServerEventState, event: Extract<ServerEventStateAction, { type: 'event' }>): ServerEventState {
    const { event: evt } = event;
    switch (evt.type) {
        case 'queue':
            return {
                ...state,
                queueItems: evt.tracks,
                trackPanel: state.trackPanel
                    ? { ...state.trackPanel, tracks: markQueuedTracks(state.trackPanel.panel === 'queue' ? evt.tracks : state.trackPanel.tracks, evt.tracks) }
                    : state.trackPanel,
            };
        case 'track_panel':
            return {
                ...state,
                trackPanel: {
                    panel: evt.panel,
                    title: evt.title,
                    hint: evt.hint,
                    tracks: markQueuedTracks(evt.tracks, state.queueItems),
                },
                trackPanelIndex: 0,
            };
        case 'memory_panel':
            return {
                ...state,
                memoryPanel: {
                    view: evt.view,
                    target: evt.target,
                    title: evt.title,
                    hint: evt.hint,
                    readOnly: Boolean(evt.read_only),
                    entries: evt.entries ?? [],
                    settings: evt.settings,
                },
                memoryPanelIndex: 0,
                memorySearchQuery: '',
                memoryEditor: null,
            };
        case 'extension_panel':
            return {
                ...state,
                extensionPanel: {
                    view: evt.view,
                    title: evt.title,
                    hint: evt.hint,
                    selectedExtension: evt.selected_extension ?? null,
                    extensions: evt.extensions,
                    detail: evt.detail,
                    setup: evt.setup,
                },
                extensionPanelIndex: Math.max(0, extensionIndex(evt)),
                extensionInputFocused: false,
            };
        case 'search_results': {
            const first = evt.tracks[0];
            return {
                ...state,
                searchItems: evt.tracks,
                ...(first ? {
                    player: {
                        name: first.title || first.name || '-',
                        artist: first.artist || '-',
                        album: first.album || '-',
                        duration_ms: first.duration_ms || 0,
                        progress_ms: 0,
                        is_playing: false,
                    },
                    coverUrl: first.album_cover_url ?? null,
                    coverImage: null,
                    coverPattern: null,
                } : {}),
            };
        }
        case 'player':
            return { ...state, player: evt.state };
        case 'cover':
            return { ...state, coverUrl: evt.url, coverImage: null, coverPattern: null };
        case 'cover_image':
            return evt.source_url === state.coverUrl ? { ...state, coverImage: evt } : state;
        case 'cover_pattern':
            return evt.source_url === state.coverUrl ? { ...state, coverPattern: evt } : state;
        case 'cover_pattern_unavailable':
            return evt.source_url === state.coverUrl
                ? {
                    ...state,
                    coverPattern: {
                        type: 'cover_pattern',
                        source_url: evt.source_url,
                        palette: [],
                        variants: {},
                        unavailable_reason: evt.reason,
                    },
                }
                : state;
        case 'confirm':
            if (event.dismissedConfirm) return state;
            return {
                ...state,
                confirm: {
                    id: evt.id,
                    tool_name: evt.tool_name,
                    tool_args: evt.tool_args ?? {},
                    message: evt.message || `Confirm ${evt.tool_name}`,
                    warning: evt.warning,
                    hide_hint: evt.hide_hint === true,
                    choices: evt.choices && evt.choices.length > 0 ? evt.choices : DEFAULT_CONFIRM_CHOICES,
                    variant: evt.variant,
                    commands: evt.commands ?? [],
                    page_index: evt.page_index,
                    page_count: evt.page_count,
                },
                confirmIndex: evt.tool_args?.preserve_selection === true ? state.confirmIndex : 0,
            };
        case 'confirm_dismiss':
            return state.confirm?.id === evt.id ? { ...state, confirm: null } : state;
        case 'auth_setup':
            return {
                ...state,
                loginSelectionIndex: evt.step === 'provider'
                    ? resolveLoginProviderSelectionIndex(evt.providers ?? [], evt.provider)
                    : 0,
            };
        case 'auth_state':
            return {
                ...state,
                authState: {
                    ready: evt.ready,
                    provider: evt.provider,
                    model: evt.model,
                    model_label: evt.model_label,
                    auth_type: evt.auth_type,
                    credential_source: evt.credential_source,
                    reason: evt.reason,
                },
            };
        case 'help_panel':
            return {
                ...state,
                helpPanel: {
                    title: evt.title,
                    hint: evt.hint,
                    commands: helpCommandsForLanguage(evt.commands, event.language),
                },
                helpPanelIndex: 0,
            };
        case 'bye':
            return { ...state, isExiting: true };
        default:
            return state;
    }
}

export function reduceServerEventState(state: ServerEventState, action: ServerEventStateAction): ServerEventState {
    if (action.type === 'event') return reduceEvent(state, action);
    const current = state[action.key];
    const next = typeof action.value === 'function'
        ? (action.value as (value: unknown) => unknown)(current)
        : action.value;
    return { ...state, [action.key]: next } as ServerEventState;
}

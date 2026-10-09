import { upsertActivity } from './activity.js';
import { shouldStartLaunchPreparing } from './launch-preparing.js';
import type { ActivityItem, ServerEvent, SessionTokenUsage } from './types.js';

export type RuntimeState = Readonly<{
    sessionId: string | null;
    tokenUsage: SessionTokenUsage;
    agentWorkingTurnId: string | null;
    activityItems: ActivityItem[];
    statusText: string;
    launchPreparing: boolean;
    recommendInputLocked: boolean;
}>;

export type RuntimeAction =
    | { type: 'event'; event: ServerEvent; rawEvent?: ServerEvent }
    | { type: 'set_status'; text: string }
    | { type: 'clear_agent_working' }
    | { type: 'replace'; state: RuntimeState };

export const createInitialRuntimeState = (statusText: string): RuntimeState => ({
    sessionId: null,
    tokenUsage: { inputTokens: 0, outputTokens: 0 },
    agentWorkingTurnId: null,
    activityItems: [],
    statusText,
    launchPreparing: false,
    recommendInputLocked: false,
});

const clearsLaunchPreparing = new Set<ServerEvent['type']>([
    'track_panel',
    'memory_panel',
    'extension_panel',
    'player',
    'confirm',
    'spotify_setup',
    'auth_setup',
    'help_panel',
    'bye',
]);

export function reduceRuntimeState(state: RuntimeState, action: RuntimeAction): RuntimeState {
    if (action.type === 'replace') return action.state;
    if (action.type === 'set_status') return { ...state, statusText: action.text };
    if (action.type === 'clear_agent_working') return { ...state, agentWorkingTurnId: null };

    const event = action.event;
    const next = clearsLaunchPreparing.has(event.type)
        ? { ...state, launchPreparing: false }
        : state;

    switch (event.type) {
        case 'session_state':
            return { ...next, sessionId: event.session_id };
        case 'usage_state':
            return {
                ...next,
                tokenUsage: {
                    inputTokens: event.input_tokens,
                    outputTokens: event.output_tokens,
                },
            };
        case 'agent_working_state':
            return {
                ...next,
                agentWorkingTurnId: event.active
                    ? event.turn_id
                    : next.agentWorkingTurnId === event.turn_id
                        ? null
                        : next.agentWorkingTurnId,
            };
        case 'activity': {
            const launchPreparing = shouldStartLaunchPreparing(event)
                ? true
                : event.status === 'success' || event.status === 'error'
                    ? false
                    : next.launchPreparing;
            return {
                ...next,
                activityItems: upsertActivity(next.activityItems, event),
                launchPreparing,
            };
        }
        case 'status':
            return {
                ...next,
                statusText: event.message,
                launchPreparing: action.rawEvent?.type === 'status'
                    ? action.rawEvent.active !== false && action.rawEvent.message === 'Preparing playback...'
                    : event.active !== false && event.message === 'Preparing playback...',
            };
        case 'input_state':
            return {
                ...next,
                recommendInputLocked: event.disabled && event.reason === 'recommendation',
            };
        case 'track_panel':
        case 'memory_panel':
        case 'extension_panel':
        case 'spotify_setup':
        case 'auth_setup':
        case 'help_panel':
            return { ...next, statusText: event.title };
        case 'bye':
            return { ...next, statusText: event.message ?? `Session saved to ${event.path}. Bye.` };
        default:
            return next;
    }
}

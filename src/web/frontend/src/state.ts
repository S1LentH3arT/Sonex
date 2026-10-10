import type {
  ConversationMessage,
  ActivityEvent,
  WebEvent,
  PlayerState,
  QueueTrack,
  Session,
  ServerEvent,
  WebLibraryEvent,
} from "./protocol";

export type State = {
  status: "starting" | "ready" | "stopped";
  error: string | null;
  activeId: string;
  viewedId: string;
  sessions: Session[];
  messages: Record<string, ConversationMessage[]>;
  user: string;
  home: string;
  player: PlayerState | null;
  queue: QueueTrack[];
  revision: number;
  auth: Extract<ServerEvent, { type: "auth_state" }> | null;
  setup: Extract<ServerEvent, { type: "auth_setup" | "spotify_setup" }> | null;
  confirm: Extract<ServerEvent, { type: "confirm" }> | null;
  panel: Extract<
    ServerEvent,
    {
      type:
        | "memory_panel"
        | "extension_panel"
        | "track_panel"
        | "proxy_state"
        | "help_panel";
    }
  > | WebLibraryEvent | null;
  working: { turnId: string; sessionId: string } | null;
  activity: ActivityEvent | null;
  pendingActivities: Record<string, ActivityEvent[]>;
  spotify: boolean;
  cover: { url: string; data: string } | null;
  coverSource: string | null;
};
export const initialState: State = {
  status: "starting",
  error: null,
  activeId: "",
  viewedId: "",
  sessions: [],
  messages: {},
  user: "Local user",
  home: "",
  player: null,
  queue: [],
  revision: 0,
  auth: null,
  setup: null,
  confirm: null,
  panel: null,
  working: null,
  activity: null,
  pendingActivities: {},
  spotify: false,
  cover: null,
  coverSource: null,
};
export type Action =
  | WebEvent
  | { type: "view"; id: string }
  | { type: "dismiss_error" | "dismiss_panel" | "dismiss_confirm" };
export function reduce(state: State, event: Action): State {
  switch (event.type) {
    case "runtime_status":
      return {
        ...state,
        status: event.status,
        error: event.status === "stopped" ? null : event.message ?? state.error,
      };
    case "web_snapshot":
      return {
        ...state,
        status: "ready",
        activeId: event.session_id,
        viewedId: event.session_id,
        sessions: event.sessions,
        messages: { ...state.messages, [event.session_id]: event.messages },
        user: event.user,
        home: event.home,
        working: null,
        confirm: null,
        panel: null,
      };
    case "web_sessions":
      return { ...state, sessions: event.sessions };
    case "web_history":
      return {
        ...state,
        messages: {
          ...state.messages,
          [event.viewed_session_id]: event.messages,
        },
      };
    case "view":
      return { ...state, viewedId: event.id, panel: null };
    case "web_queue":
      return { ...state, queue: event.items, revision: event.revision };
    case "chat": {
      const id = event.session_id || state.activeId;
      const turnKey = event.turn_id ? `${id}:${event.turn_id}` : "";
      const pendingActivities = turnKey
        ? state.pendingActivities[turnKey] ?? []
        : [];
      const message: ConversationMessage = {
        role: event.role,
        content: event.text,
        document: event.document,
        tone: event.tone,
        turn_id: event.turn_id,
        ...(event.role === "agent" && pendingActivities.length
          ? { activities: pendingActivities }
          : {}),
      };
      const remainingActivities = { ...state.pendingActivities };
      if (event.role === "agent" && event.stream && turnKey)
        delete remainingActivities[turnKey];
      return {
        ...state,
        pendingActivities: remainingActivities,
        messages: {
          ...state.messages,
          [id]: [...(state.messages[id] ?? []), message],
        },
        sessions: state.sessions.map((s) =>
        s.id === id && s.title === "New session" && event.role === "user"
            ? { ...s, title: event.text.slice(0, 60) }
            : s,
        ),
      };
    }
    case "player":
      return { ...state, player: event.state };
    case "cover":
      return {
        ...state,
        coverSource: event.url,
        cover: state.cover?.url === event.url ? state.cover : null,
      };
    case "cover_image":
      return event.source_url === state.coverSource
        ? {
            ...state,
            cover: {
              url: event.source_url,
              data: `data:image/png;base64,${event.data}`,
            },
          }
        : state;
    case "auth_state":
      return { ...state, auth: event };
    case "auth_setup":
    case "spotify_setup":
      return { ...state, setup: event.active === false ? null : event };
    case "confirm":
      return { ...state, confirm: event };
    case "confirm_dismiss":
      return state.confirm?.id === event.id
        ? { ...state, confirm: null }
        : state;
    case "agent_working_state":
      return event.active
        ? {
            ...state,
            working: {
              turnId: event.turn_id,
              sessionId: event.session_id || state.activeId,
            },
            activity: null,
          }
        : state.working?.turnId === event.turn_id
          ? { ...state, working: null, activity: null }
          : state;
    case "activity": {
      const sessionId = event.session_id || state.activeId;
      const turnKey = sessionId && event.turn_id ? `${sessionId}:${event.turn_id}` : "";
      if (!turnKey) return { ...state, activity: event };
      const records = state.pendingActivities[turnKey] ?? [];
      const index = records.findIndex((item) => item.id === event.id);
      const shouldRecord = ["tool", "confirm", "error"].includes(event.kind);
      const pendingActivities = { ...state.pendingActivities };
      if (shouldRecord) {
        pendingActivities[turnKey] =
          index < 0
            ? [...records, event]
            : records.map((item, itemIndex) =>
                itemIndex === index ? event : item,
              );
      }
      return { ...state, activity: event, pendingActivities };
    }
    case "provider_mode":
      return {
        ...state,
        spotify: event.provider === "spotify" && event.enabled,
      };
    case "memory_panel":
    case "extension_panel":
    case "track_panel":
    case "help_panel":
      return { ...state, panel: event };
    case "web_library":
      return { ...state, panel: event };
    case "proxy_state":
      return { ...state, panel: event.close ? null : event };
    case "error":
      return { ...state, error: event.message };
    case "dismiss_error":
      return { ...state, error: null };
    case "dismiss_panel":
      return { ...state, panel: null };
    case "dismiss_confirm":
      return { ...state, confirm: null };
    default:
      return state;
  }
}

export function position(player: PlayerState, now: number): number {
  const base = player.progress_ms ?? 0;
  const anchor = player.progress_anchor_ms ?? player.timestamp;
  const elapsed =
    player.is_playing &&
    !player.progress_sync_lost &&
    !player.paused_for_cache &&
    anchor
      ? Math.max(0, now - anchor)
      : 0;
  return Math.min(player.duration_ms || base, Math.max(0, base + elapsed));
}
export function clock(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

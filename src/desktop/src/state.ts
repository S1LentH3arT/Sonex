import type {
  ChatTranscriptMessage,
  DesktopEvent,
  PlayerState,
  QueueTrack,
  Session,
  ServerEvent,
} from "./protocol";

export type State = {
  status: "starting" | "ready" | "stopped";
  error: string | null;
  activeId: string;
  viewedId: string;
  sessions: Session[];
  messages: Record<string, ChatTranscriptMessage[]>;
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
  > | null;
  working: { turnId: string; sessionId: string } | null;
  activity: string;
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
  user: "本地用户",
  home: "",
  player: null,
  queue: [],
  revision: 0,
  auth: null,
  setup: null,
  confirm: null,
  panel: null,
  working: null,
  activity: "",
  spotify: false,
  cover: null,
  coverSource: null,
};
export type Action =
  | DesktopEvent
  | { type: "view"; id: string }
  | { type: "dismiss_error" | "dismiss_panel" | "dismiss_confirm" };
export function reduce(state: State, event: Action): State {
  switch (event.type) {
    case "runtime_status":
      return {
        ...state,
        status: event.status,
        error: event.message ?? state.error,
      };
    case "desktop_snapshot":
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
    case "desktop_sessions":
      return { ...state, sessions: event.sessions };
    case "desktop_history":
      return {
        ...state,
        messages: {
          ...state.messages,
          [event.viewed_session_id]: event.messages,
        },
      };
    case "view":
      return { ...state, viewedId: event.id, panel: null };
    case "desktop_queue":
      return { ...state, queue: event.items, revision: event.revision };
    case "chat": {
      const id = event.session_id || state.activeId;
      const message: ChatTranscriptMessage = {
        role: event.role,
        content: event.text,
        document: event.document,
        tone: event.tone,
      };
      return {
        ...state,
        messages: {
          ...state.messages,
          [id]: [...(state.messages[id] ?? []), message],
        },
        sessions: state.sessions.map((s) =>
          s.id === id && s.title === "新会话" && event.role === "user"
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
            activity: "正在思考…",
          }
        : state.working?.turnId === event.turn_id
          ? { ...state, working: null, activity: "" }
          : state;
    case "activity":
      return event.status === "pending"
        ? { ...state, activity: event.detail || event.title }
        : state;
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

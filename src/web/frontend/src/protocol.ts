// These type-only imports keep the browser bundle independent of the Ink renderer.
export type {
  ServerEvent,
  ClientEvent,
  PlayerState,
  ChatTranscriptMessage,
  ChatDocument,
  TrackPanelTrack,
} from "../../../cli/src/types.js";
import type {
  ServerEvent,
  ChatTranscriptMessage,
} from "../../../cli/src/types.js";

export type Session = { id: string; title: string; updated_at: number };
export type ActivityEvent = Extract<ServerEvent, { type: "activity" }> & {
  session_id?: string;
  turn_id?: string;
};
export type ConversationMessage = ChatTranscriptMessage & {
  activities?: ActivityEvent[];
  turn_id?: string;
};
export type WebLibraryTrack = {
  path: string;
  name: string;
  title: string;
  artist: string;
  provider: "local";
};
export type WebLibraryEvent = {
  type: "web_library";
  title: "Library";
  path: string;
  tracks: WebLibraryTrack[];
  truncated: boolean;
};
export type QueueTrack = {
  entry_id: string;
  ref?: string;
  name?: string;
  title?: string;
  artist?: string;
  provider?: string;
  duration_ms?: number;
};
export type WebEvent =
  | (ServerEvent & { session_id?: string; turn_id?: string })
  | {
      type: "web_snapshot";
      session_id: string;
      messages: ChatTranscriptMessage[];
      sessions: Session[];
      user: string;
      home: string;
      protocol_version: number;
    }
  | { type: "web_sessions"; sessions: Session[] }
  | {
      type: "web_history";
      viewed_session_id: string;
      messages: ChatTranscriptMessage[];
    }
  | { type: "web_queue"; revision: number; items: QueueTrack[] }
  | WebLibraryEvent
  | {
      type: "runtime_status";
      status: "starting" | "ready" | "stopped";
      message?: string;
    };
export type WebCommand = {
  type: "web";
  action:
    | "snapshot"
    | "library"
    | "library_set_path"
    | "library_play"
    | "sessions"
    | "read_session"
    | "new_session"
    | "chat"
    | "command"
    | "player"
    | "queue";
  [key: string]: unknown;
};

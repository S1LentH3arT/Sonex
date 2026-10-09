// These are type-only imports: the desktop never loads the Ink renderer.
export type {
  ServerEvent,
  ClientEvent,
  PlayerState,
  ChatTranscriptMessage,
  ChatDocument,
  TrackPanelTrack,
} from "../../cli/src/types.js";
import type {
  ServerEvent,
  ChatTranscriptMessage,
} from "../../cli/src/types.js";

export type Session = { id: string; title: string; updated_at: number };
export type QueueTrack = {
  entry_id: string;
  ref?: string;
  name?: string;
  title?: string;
  artist?: string;
  provider?: string;
  duration_ms?: number;
};
export type DesktopEvent =
  | (ServerEvent & { session_id?: string })
  | {
      type: "desktop_snapshot";
      session_id: string;
      messages: ChatTranscriptMessage[];
      sessions: Session[];
      user: string;
      home: string;
      protocol_version: number;
    }
  | { type: "desktop_sessions"; sessions: Session[] }
  | {
      type: "desktop_history";
      viewed_session_id: string;
      messages: ChatTranscriptMessage[];
    }
  | { type: "desktop_queue"; revision: number; items: QueueTrack[] }
  | {
      type: "runtime_status";
      status: "starting" | "ready" | "stopped";
      message?: string;
    };
export type DesktopCommand = {
  type: "desktop";
  action:
    | "snapshot"
    | "sessions"
    | "read_session"
    | "new_session"
    | "chat"
    | "command"
    | "player"
    | "queue";
  [key: string]: unknown;
};

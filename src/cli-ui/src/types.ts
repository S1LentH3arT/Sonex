/**
 * Describes the server event type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type ServerEvent =
    | { type: "chat"; role: ChatRole; text: string }
    | { type: "activity"; id: string; kind: ActivityKind; title: string; detail?: string | null; status?: ActivityStatus | null; timestamp: number }
    | { type: "status"; phase: string; message: string; tokens?: number | null; elapsed_ms?: number | null; active?: boolean | null; step?: number; max_steps?: number }
    | { type: "queue"; tracks: Array<{ index: string; title: string; artist: string; duration: string }> }
    | { type: "search_results"; tracks: TrackSummary[] }
    | { type: "player"; state: PlayerState }
    | { type: "cover"; url: string }
    | CoverPatternEvent
    | { type: "error"; message: string; detail?: string | null; recoverable?: boolean | null }
    | { type: "confirm"; id: string; tool_name: string; tool_args: Record<string, unknown>; message?: string | null; choices?: ConfirmChoice[] | null }
    | { type: "spotify_setup"; step: string; title: string; message: string; prompt?: string | null; mask?: boolean | null; active?: boolean | null }
    | { type: "auth_setup"; provider: string; step: string; title: string; message: string; prompt?: string | null; mask?: boolean | null; active?: boolean | null; methods?: AuthMethodChoice[] | null; providers?: AuthMethodChoice[] | null; models?: AuthMethodChoice[] | null }
    | { type: "auth_state"; ready: boolean; provider: string; model: string; auth_type: string; credential_source: string; reason?: string | null }
    | { type: "help_panel"; title: string; hint: string; commands: HelpCommand[] }
    | { type: "bye"; path: string; message?: string | null };

/**
 * Describes the cover pattern event type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type CoverPatternEvent = {
    type: "cover_pattern";
    source_url: string;
    palette: string[];
    variants: Partial<Record<32 | 48 | 64, number[][]>>;
    source_hash?: string;
    generated_at?: number;
};

/**
 * Describes the client event type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type ClientEvent =
    | { type: "user_input"; text: string }
    | { type: "confirm_result"; id: string; decision: string }
    | { type: "setup_input"; value: string }
    | { type: "auth_setup_input"; value: string }
    | { type: "bye"; messages: ChatItem[]; reason: string };

/**
 * Describes the confirm choice type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type ConfirmChoice = {
    value: string;
    label: string;
    description?: string;
    input?: {
        placeholder: string;
    };
};

/**
 * Describes the confirm state type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type ConfirmState = {
    id: string;
    tool_name: string;
    tool_args: Record<string, unknown>;
    message: string;
    choices: ConfirmChoice[];
} | null;

/**
 * Describes the spotify setup state type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type SpotifySetupState = {
    step: string;
    title: string;
    message: string;
    prompt?: string | null;
    mask?: boolean | null;
    active: boolean;
} | null;

/**
 * Describes the auth method choice type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type AuthMethodChoice = {
    value: string;
    label: string;
    provider?: string;
};

/**
 * Describes the auth setup state type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type AuthSetupState = {
    provider: string;
    step: string;
    title: string;
    message: string;
    prompt?: string | null;
    mask?: boolean | null;
    active: boolean;
    methods?: AuthMethodChoice[] | null;
    providers?: AuthMethodChoice[] | null;
    models?: AuthMethodChoice[] | null;
} | null;

/**
 * Describes the auth runtime state type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type AuthRuntimeState = {
    ready: boolean;
    provider: string;
    model: string;
    auth_type: string;
    credential_source: string;
    reason?: string | null;
};

/**
 * Describes the chat role type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type ChatRole = "user" | "agent";

/**
 * Describes the activity kind type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type ActivityKind = "tool" | "status" | "error" | "confirm";

/**
 * Describes the activity status type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type ActivityStatus = "pending" | "success" | "error";

/**
 * Describes the activity item type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type ActivityItem = {
    id: string;
    kind: ActivityKind;
    title: string;
    detail?: string | null;
    status?: ActivityStatus | null;
    timestamp: number;
};

/**
 * Describes the player state type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type PlayerState = {
    name: string;
    artist: string;
    album: string;
    duration_ms: number;
    progress_ms?: number;
    timestamp?: number;
    started_at?: number;
    is_playing?: boolean;
    provider?: string | null;
    player?: "mpv" | "cvlc" | string | null;
    session_id?: string | null;
    ended?: boolean | null;
    volume_percent?: number | null;
    source?: "local" | "youtube" | "spotify" | "apple_music" | string | null;
};

/**
 * Describes the track summary type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type TrackSummary = {
    index: string;
    name: string;
    title: string;
    artist: string;
    album: string;
    duration: string;
    duration_ms: number;
    uri?: string | null;
    spotify_url?: string | null;
    album_cover_url?: string | null;
    recommendation_reason?: string | null;
};

/**
 * Describes the chat bubble props type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type ChatBubbleProps = {
    role: ChatRole;
    content: string;
};

/**
 * Describes the chat item type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type ChatItem = {
    role: ChatRole;
    content: string;
};

/**
 * Describes the help command type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type HelpCommand = {
    name: string;
    usage: string;
    description: string;
};

/**
 * Describes the help panel state type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type HelpPanelState = {
    title: string;
    hint: string;
    commands: HelpCommand[];
} | null;

/**
 * Describes the layout mode type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type LayoutMode = "compact" | "full";

/**
 * Describes the player pane variant type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type PlayerPaneVariant = "compact" | "full";

/**
 * Describes the prompt input props type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type PromptInputProps = {
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    focus: boolean;
    placeholder: string;
    mask?: string;
    inputRevision?: number;
};

/**
 * Describes the login screen props type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type LoginScreenProps = {
    authSetup: AuthSetupState;
    selectedIndex: number;
    apiKeyInput: string;
    setApiKeyInput: (value: string) => void;
    onApiKeySubmit: (value: string) => void;
};

/**
 * Describes the slash command suggestion type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type SlashCommandSuggestion = {
    name: string;
    usage: string;
    description: string;
    needsArgument: boolean;
    aliases?: string[];
};

/**
 * Describes the visible chat window type.
 *
 * Documents the shape shared across types.ts call sites.
 */
export type VisibleChatWindow = {
    items: ChatItem[];
    hasHiddenAbove: boolean;
    hasHiddenBelow: boolean;
    maxScrollOffset: number;
};

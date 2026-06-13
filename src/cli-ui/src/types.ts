export type ServerEvent =
    | { type: "chat"; role: ChatRole; text: string }
    | { type: "activity"; id: string; kind: ActivityKind; title: string; detail?: string | null; status?: ActivityStatus | null; timestamp: number }
    | { type: "status"; phase: string; message: string; tokens?: number | null; elapsed_ms?: number | null; active?: boolean | null; step?: number; max_steps?: number }
    | { type: "queue"; tracks: Array<{ index: string; title: string; artist: string; duration: string }> }
    | { type: "search_results"; tracks: TrackSummary[] }
    | { type: "player"; state: PlayerState }
    | { type: "cover"; url: string }
    | CoverPatternEvent
    | CoverPatternUnavailableEvent
    | { type: "error"; message: string; detail?: string | null; recoverable?: boolean | null }
    | { type: "confirm"; id: string; tool_name: string; tool_args: Record<string, unknown>; message?: string | null; choices?: ConfirmChoice[] | null }
    | { type: "spotify_setup"; step: string; title: string; message: string; prompt?: string | null; mask?: boolean | null; active?: boolean | null }
    | { type: "auth_setup"; provider: string; step: string; title: string; message: string; prompt?: string | null; mask?: boolean | null; active?: boolean | null; methods?: AuthMethodChoice[] | null; providers?: AuthMethodChoice[] | null; models?: AuthMethodChoice[] | null }
    | { type: "auth_state"; ready: boolean; provider: string; model: string; auth_type: string; credential_source: string; reason?: string | null }
    | { type: "help_panel"; title: string; hint: string; commands: HelpCommand[] }
    | { type: "bye"; path: string; message?: string | null };

export type CoverPatternEvent = {
    type: "cover_pattern";
    source_url: string;
    palette: string[];
    variants: Partial<Record<`${number}`, number[][]>>;
    bead_catalog?: {
        brand: string;
        product_line: string;
        diameter_mm: number;
        version: string;
        algorithm_version: string;
        colors: Array<{ palette_index: number; code: string; name: string; hex: string }>;
        usage_by_variant: Partial<Record<`${number}`, Array<{ palette_index: number; count: number }>>>;
    };
    unavailable_reason?: "invalid_brand" | "catalog_invalid" | "decode_failed" | "generation_failed";
    source_hash?: string;
    generated_at?: number;
};

export type CoverPatternUnavailableEvent = {
    type: "cover_pattern_unavailable";
    source_url: string;
    reason: "invalid_brand" | "catalog_invalid" | "decode_failed" | "generation_failed";
};

export type ClientEvent =
    | { type: "user_input"; text: string }
    | { type: "confirm_result"; id: string; decision: string }
    | { type: "setup_input"; value: string }
    | { type: "auth_setup_input"; value: string }
    | { type: "bye"; messages: ChatItem[]; reason: string };

export type ConfirmChoice = {
    value: string;
    label: string;
    description?: string;
    input?: {
        placeholder: string;
    };
};

export type ConfirmState = {
    id: string;
    tool_name: string;
    tool_args: Record<string, unknown>;
    message: string;
    choices: ConfirmChoice[];
} | null;

export type SpotifySetupState = {
    step: string;
    title: string;
    message: string;
    prompt?: string | null;
    mask?: boolean | null;
    active: boolean;
} | null;

export type AuthMethodChoice = {
    value: string;
    label: string;
    provider?: string;
};

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

export type AuthRuntimeState = {
    ready: boolean;
    provider: string;
    model: string;
    auth_type: string;
    credential_source: string;
    reason?: string | null;
};

export type ChatRole = "user" | "agent";

export type ActivityKind = "tool" | "status" | "error" | "confirm";

export type ActivityStatus = "pending" | "success" | "error";

export type ActivityItem = {
    id: string;
    kind: ActivityKind;
    title: string;
    detail?: string | null;
    status?: ActivityStatus | null;
    timestamp: number;
};

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

export type ChatBubbleProps = {
    role: ChatRole;
    content: string;
};

export type ChatItem = {
    role: ChatRole;
    content: string;
};

export type HelpCommand = {
    name: string;
    usage: string;
    description: string;
};

export type HelpPanelState = {
    title: string;
    hint: string;
    commands: HelpCommand[];
} | null;

export type LayoutMode = "compact" | "full";

export type PlayerPaneVariant = "compact" | "full";

export type PromptInputProps = {
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    focus: boolean;
    placeholder: string;
    mask?: string;
    inputRevision?: number;
};

export type LoginScreenProps = {
    authSetup: AuthSetupState;
    selectedIndex: number;
    apiKeyInput: string;
    setApiKeyInput: (value: string) => void;
    onApiKeySubmit: (value: string) => void;
};

export type SlashCommandSuggestion = {
    name: string;
    usage: string;
    description: string;
    needsArgument: boolean;
    aliases?: string[];
};

export type VisibleChatWindow = {
    items: ChatItem[];
    hasHiddenAbove: boolean;
    hasHiddenBelow: boolean;
    maxScrollOffset: number;
};

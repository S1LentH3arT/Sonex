export type ServerEvent =
    | { type: "chat"; role: ChatRole; text: string; theme?: ChatTheme | null; tone?: ChatTone | null; segments?: ChatSegment[] | null }
    | { type: "session_state"; session_id: string }
    | { type: "usage_state"; input_tokens: number; output_tokens: number }
    | { type: "agent_working_state"; turn_id: string; active: boolean }
    | { type: "activity"; id: string; kind: ActivityKind; title: string; detail?: string | null; status?: ActivityStatus | null; timestamp: number }
    | { type: "status"; phase: string; message: string; active?: boolean | null; step?: number; max_steps?: number }
    | { type: "input_state"; disabled: boolean; reason?: "recommendation" | null }
    | { type: "queue"; tracks: Array<{ index: string; title: string; artist: string; duration: string }> }
    | { type: "track_panel"; panel: "queue" | "playlist"; title: string; hint?: string | null; tracks: TrackPanelTrack[] }
    | { type: "search_results"; tracks: TrackSummary[] }
    | { type: "player"; state: PlayerState }
    | { type: "spotify_mode"; enabled: boolean; device_id?: string | null; device_name?: string | null }
    | { type: "provider_mode"; provider: "normal" | "spotify" | "apple"; enabled: boolean; storefront?: string | null; connection_status?: string | null }
    | { type: "cover"; url: string }
    | CoverPatternEvent
    | CoverPatternUnavailableEvent
    | { type: "error"; message: string; detail?: string | null; recoverable?: boolean | null }
    | { type: "confirm"; id: string; tool_name: string; tool_args: Record<string, unknown>; message?: string | null; warning?: string | null; hide_hint?: boolean | null; choices?: ConfirmChoice[] | null; variant?: "tool_call_review" | null; commands?: string[] | null; page_index?: number | null; page_count?: number | null }
    | { type: "spotify_setup"; step: string; title: string; message: string; prompt?: string | null; mask?: boolean | null; active?: boolean | null }
    | { type: "auth_setup"; provider: string; step: string; title: string; message: string; prompt?: string | null; placeholder?: string | null; help_text?: string | null; mask?: boolean | null; active?: boolean | null; methods?: AuthMethodChoice[] | null; providers?: AuthMethodChoice[] | null; models?: AuthMethodChoice[] | null }
    | { type: "auth_state"; ready: boolean; provider: string; model: string; model_label?: string | null; auth_type: string; credential_source: string; reason?: string | null }
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

export type UiLanguage = "en" | "zh-CN";

export type LanguagePanelState = {
    active: boolean;
    selected: UiLanguage;
    saveError?: string | null;
} | null;

export type ClientEvent =
    | { type: "user_input"; text: string }
    | { type: "agent_turn_interrupt"; turn_id: string }
    | { type: "internal_command"; text: string }
    | { type: "track_panel_action"; action: "queue_add" | "play"; track: TrackPanelTrack; panel: "queue" | "playlist"; title: string }
    | { type: "confirm_result"; id: string; decision: string }
    | { type: "setup_input"; value: string }
    | { type: "auth_setup_input"; value: string }
    | { type: "bye"; messages: ChatTranscriptMessage[]; reason: string };

export type MusicCandidateDisplay = {
    kind: "music_candidate";
    artist: string;
    album: string;
    title: string;
};

export type ConfirmChoiceDisplay = MusicCandidateDisplay;

export type ConfirmChoice = {
    value: string;
    label: string;
    description?: string;
    disabled?: boolean;
    disabled_reason?: string;
    display?: ConfirmChoiceDisplay;
    track_count?: number;
    input?: {
        placeholder: string;
    };
};

export type ConfirmState = {
    id: string;
    tool_name: string;
    tool_args: Record<string, unknown>;
    message: string;
    warning?: string | null;
    hide_hint?: boolean;
    choices: ConfirmChoice[];
    variant?: "tool_call_review" | null;
    commands?: string[];
    page_index?: number | null;
    page_count?: number | null;
} | null;

export type SpotifySetupState = {
    step: string;
    title: string;
    message: string;
    prompt?: string | null;
    mask?: boolean | null;
    active: boolean;
} | null;

export type SpotifyModeState = {
    enabled: boolean;
    device_id?: string | null;
    device_name?: string | null;
};

export type ProviderModeState = {
    provider: "normal" | "spotify" | "apple";
    enabled: boolean;
    storefront?: string | null;
    connection_status?: string | null;
};

export type AuthMethodChoice = {
    value: string;
    label: string;
    provider?: string;
    description?: string;
    connected?: boolean;
    connection_status?: "active" | "saved" | "missing";
};

export type AuthSetupState = {
    provider: string;
    step: string;
    title: string;
    message: string;
    prompt?: string | null;
    placeholder?: string | null;
    help_text?: string | null;
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
    model_label?: string | null;
    auth_type: string;
    credential_source: string;
    reason?: string | null;
};

export type SessionTokenUsage = {
    inputTokens: number;
    outputTokens: number;
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
    progress_anchor_ms?: number;
    timestamp?: number;
    started_at?: number;
    is_playing?: boolean;
    playback_status?: "starting" | "playing" | "paused" | "ended" | string | null;
    progress_source?: "spotify_pending" | "spotify_live" | "local_player" | string | null;
    progress_sync_lost?: boolean;
    paused_for_cache?: boolean;
    diagnostic_notice?: "clock_drift" | "cache_pause" | "ipc_failure" | "audio_output_changed" | string | null;
    provider?: string | null;
    player?: "mpv" | "cvlc" | string | null;
    session_id?: string | null;
    ended?: boolean | null;
    volume_percent?: number | null;
    is_liked?: boolean | null;
    is_in_playlist?: boolean | null;
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

export type ChatTheme = "spotify" | "muted";

export type ChatTone = "system" | "warning" | "error";

export type ChatSegment = {
    text: string;
    style: "tool_name" | "tool_value";
};

export type ChatBubbleProps = {
    role: ChatRole;
    content: string;
    contentWidth: number;
    theme?: ChatTheme | null;
    tone?: ChatTone | null;
    segments?: ChatSegment[] | null;
};

export type ChatMessageItem = {
    type: "message";
    role: ChatRole;
    content: string;
    theme?: ChatTheme | null;
    tone?: ChatTone | null;
    segments?: ChatSegment[] | null;
};

export type ChatTranscriptMessage = Pick<ChatMessageItem, "role" | "content" | "theme" | "tone" | "segments">;

export type InfoBannerItem = {
    type: "info_banner";
    authState: AuthRuntimeState;
    cwd: string;
    sessionId: string | null;
    tokenUsage: SessionTokenUsage;
};

export type ChatItem = ChatMessageItem | InfoBannerItem;

export type HelpCommand = {
    name: string;
    usage: string;
    description: string;
    enabled?: boolean;
};

export type HelpPanelState = {
    title: string;
    hint: string;
    commands: HelpCommand[];
} | null;

export type TrackPanelTrack = {
    index: string;
    title: string;
    artist: string;
    duration: string;
    name?: string;
    album?: string;
    duration_ms?: number;
    provider?: string;
    source?: string;
    source_app?: string;
    cache_id?: string;
    uri?: string;
    url?: string;
    stream_url?: string;
    youtube_url?: string;
    spotify_url?: string;
    apple_music_url?: string;
    audio_path?: string;
    file_path?: string;
    path?: string;
    album_cover_url?: string;
    id?: string;
    queued?: boolean;
};

export type TrackPanelState = {
    panel: "queue" | "playlist";
    title: string;
    hint?: string | null;
    tracks: TrackPanelTrack[];
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
    backgroundColor?: string;
    backgroundWidth?: number;
    backgroundPaddingX?: number;
};

export type LoginScreenProps = {
    authSetup: AuthSetupState;
    selectedIndex: number;
    apiKeyInput: string;
    setApiKeyInput: (value: string) => void;
    onApiKeySubmit: (value: string) => void;
};

export type LanguagePanelProps = {
    panel: LanguagePanelState;
    activeLanguage: UiLanguage;
    selectedIndex: number;
};

export type SlashCommandSuggestion = {
    name: string;
    usage: string;
    description: string;
    needsArgument: boolean;
    aliases?: string[];
    enabled?: boolean;
};

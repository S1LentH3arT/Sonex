/**
 * Defines the full layout min columns constant.
 *
 * Stores stable configuration or display data consumed by layout.ts.
 */
export const FULL_LAYOUT_MIN_COLUMNS = 114;
/**
 * Defines the full layout min rows constant.
 *
 * Stores stable configuration or display data consumed by layout.ts.
 */
export const FULL_LAYOUT_MIN_ROWS = 24;

/**
 * Describes the preferred layout type.
 *
 * Documents the shape shared across layout.ts call sites.
 */
export type PreferredLayout = "compact" | "full";
/**
 * Describes the shell layout type.
 *
 * Documents the shape shared across layout.ts call sites.
 */
export type ShellLayout = "chat" | "full" | "miniPlayer";
/**
 * Describes the small playback focus type.
 *
 * Documents the shape shared across layout.ts call sites.
 */
export type SmallPlaybackFocus = "player" | "chat";
/**
 * Describes the mini player chrome type.
 *
 * Documents the shape shared across layout.ts call sites.
 */
export type MiniPlayerChrome = {
    inputOnly: boolean;
    showConversation: boolean;
    showStatus: boolean;
    switchHint: string;
};
/**
 * Describes the player event focus input type.
 *
 * Documents the shape shared across layout.ts call sites.
 */
export type PlayerEventFocusInput = {
    wasPlaying: boolean;
    isPlaying: boolean;
    currentFocus: SmallPlaybackFocus;
};

/**
 * Describes the terminal size type.
 *
 * Documents the shape shared across layout.ts call sites.
 */
export type TerminalSize = {
    columns: number | null;
    rows: number | null;
};

/**
 * Can use full playback layout.
 *
 * Coordinates the can use full playback layout operation for the CLI UI runtime.
 *
 * @param size Input value used by the can use full playback layout operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function canUseFullPlaybackLayout(size: TerminalSize): boolean {
    return (size.columns ?? 0) >= FULL_LAYOUT_MIN_COLUMNS && (size.rows ?? 0) >= FULL_LAYOUT_MIN_ROWS;
}

/**
 * Resolve shell layout.
 *
 * Coordinates the resolve shell layout operation for the CLI UI runtime.
 *
 * @param isPlaying,smallPlaybackFocus, Input value used by the resolve shell layout operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function resolveShellLayout({
    isPlaying,
    smallPlaybackFocus,
}: TerminalSize & {
    isPlaying: boolean;
    preferredLayout: PreferredLayout;
    smallPlaybackFocus: SmallPlaybackFocus;
}): ShellLayout {
    if (!isPlaying) {
        return "chat";
    }
    return smallPlaybackFocus === "chat" ? "chat" : "miniPlayer";
}

/**
 * Resolve mini player chrome.
 *
 * Coordinates the resolve mini player chrome operation for the CLI UI runtime.
 *
 * @param layout,smallPlaybackFocus, Input value used by the resolve mini player chrome operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function resolveMiniPlayerChrome({
    layout,
    smallPlaybackFocus,
}: {
    layout: ShellLayout;
    smallPlaybackFocus: SmallPlaybackFocus;
}): MiniPlayerChrome {
    /**
     * Defines the is mini player constant.
     *
     * Stores stable configuration or display data consumed by layout.ts.
     */
    const isMiniPlayer = layout === "miniPlayer";
    return {
        inputOnly: isMiniPlayer,
        showConversation: !isMiniPlayer,
        showStatus: !isMiniPlayer,
        switchHint: smallPlaybackFocus === "player" ? "Tab to switch to chat" : "Tab to switch to player",
    };
}

/**
 * Resolve player event focus.
 *
 * Coordinates the resolve player event focus operation for the CLI UI runtime.
 *
 * @param wasPlaying,isPlaying,currentFocus, Input value used by the resolve player event focus operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function resolvePlayerEventFocus({
    wasPlaying,
    isPlaying,
    currentFocus,
}: PlayerEventFocusInput): SmallPlaybackFocus {
    if (!wasPlaying && isPlaying) {
        return "player";
    }
    return currentFocus;
}

/**
 * Should return to chat after submit.
 *
 * Coordinates the should return to chat after submit operation for the CLI UI runtime.
 *
 * @param layout,commandName, Input value used by the should return to chat after submit operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function shouldReturnToChatAfterSubmit({
    layout,
    commandName,
}: {
    layout: ShellLayout;
    commandName?: string | null;
}): boolean {
    void commandName;
    return layout !== "miniPlayer" && false;
}

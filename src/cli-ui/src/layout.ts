export const FULL_LAYOUT_MIN_COLUMNS = 114;
export const FULL_LAYOUT_MIN_ROWS = 24;

export type PreferredLayout = "compact" | "full";
export type ShellLayout = "chat" | "full" | "miniPlayer";
export type SmallPlaybackFocus = "player" | "chat";
export type MiniPlayerChrome = {
    inputOnly: boolean;
    showConversation: boolean;
    showStatus: boolean;
    switchHint: string;
};
export type PlayerEventFocusInput = {
    wasPlaying: boolean;
    isPlaying: boolean;
    currentFocus: SmallPlaybackFocus;
};

export type TerminalSize = {
    columns: number | null;
    rows: number | null;
};

export function canUseFullPlaybackLayout(size: TerminalSize): boolean {
    return (size.columns ?? 0) >= FULL_LAYOUT_MIN_COLUMNS && (size.rows ?? 0) >= FULL_LAYOUT_MIN_ROWS;
}

export function resolveShellLayout({
    columns,
    rows,
    isPlaying,
    preferredLayout,
    smallPlaybackFocus,
}: TerminalSize & {
    isPlaying: boolean;
    preferredLayout: PreferredLayout;
    smallPlaybackFocus: SmallPlaybackFocus;
}): ShellLayout {
    if (!isPlaying || preferredLayout === "compact") {
        return "chat";
    }

    if (canUseFullPlaybackLayout({columns, rows})) {
        return "full";
    }

    return smallPlaybackFocus === "chat" ? "chat" : "miniPlayer";
}

export function resolveMiniPlayerChrome({
    layout,
    smallPlaybackFocus,
}: {
    layout: ShellLayout;
    smallPlaybackFocus: SmallPlaybackFocus;
}): MiniPlayerChrome {
    const isMiniPlayer = layout === "miniPlayer";
    return {
        inputOnly: isMiniPlayer,
        showConversation: !isMiniPlayer,
        showStatus: !isMiniPlayer,
        switchHint: smallPlaybackFocus === "player" ? "Tab to switch to chat" : "Tab to switch to player",
    };
}

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

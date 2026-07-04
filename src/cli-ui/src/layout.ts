import type { PlayerState } from './types.js';

export type ShellRegion = 'chat' | 'miniPlayer' | 'spotifyImmersive';

export type PlayerRegionTransition = {
    region: ShellRegion;
    sessionActive: boolean;
};

export type TerminalSize = {
    columns: number | null;
    rows: number | null;
};

export type ChatHeaderVariant = 'full' | 'compact';

export type TerminalLinePosition = {
    row: number;
    column: number;
    width: number;
};

export type MiniPlayerLayout = {
    mode: 'artwork' | 'infoOnly';
    contentColumns: number;
    contentRows: number;
    infoWidth: number;
    infoLeftPadding: number;
    infoTop: number;
    gap: number;
    coverWidth: number;
    progressSlot: TerminalLinePosition;
    statusIconSlot: TerminalLinePosition;
};

export type SpotifyImmersiveLayout = {
    topPadding: number;
    progressSlot: TerminalLinePosition;
    deviceSlot: TerminalLinePosition;
};

const CHAT_HEADER_FULL_MIN_COLUMNS = 72;
const MINI_COLUMN_GAP = 1;
const MINI_INFO_RATIO = 0.32;
const MINI_INFO_MIN_COLUMNS = 24;
const MINI_INFO_MAX_COLUMNS = 40;
const MINI_INFO_LEFT_PADDING = 4;
const MINI_COVER_MIN_COLUMNS = 32;
const MINI_COVER_MIN_ROWS = 16;
const MINI_COVER_TARGET_COLUMNS = 80;
const MINI_CONTENT_START_ROW = 1;
const MINI_CONTENT_START_COLUMN = 1;
const MINI_INFO_ROWS = 4;
const SPOTIFY_IMMERSIVE_ROWS = 10;
const SPOTIFY_PROGRESS_MIN_COLUMNS = 18;
const SPOTIFY_PROGRESS_MAX_COLUMNS = 48;

export function resolveChatHeaderVariant(columns: number | null): ChatHeaderVariant {
    return (columns ?? 0) >= CHAT_HEADER_FULL_MIN_COLUMNS ? 'full' : 'compact';
}

export function resolveMiniPlayerLayout(size: TerminalSize): MiniPlayerLayout {
    const columns = Math.max(0, size.columns ?? 0);
    const rows = Math.max(0, size.rows ?? 0);
    const contentColumns = columns;
    const contentRows = rows;
    const hasArtworkSpace = contentColumns >= MINI_INFO_MIN_COLUMNS + MINI_COLUMN_GAP + MINI_COVER_MIN_COLUMNS
        && contentRows >= MINI_COVER_MIN_ROWS;
    const mode = hasArtworkSpace ? 'artwork' : 'infoOnly';
    const gap = hasArtworkSpace ? MINI_COLUMN_GAP : 0;
    const availableSplitColumns = Math.max(0, contentColumns - gap);
    const targetCoverRowsFit = contentRows >= MINI_COVER_TARGET_COLUMNS / 2;
    const priorityCoverWidth = targetCoverRowsFit
        ? Math.min(MINI_COVER_TARGET_COLUMNS, Math.max(MINI_COVER_MIN_COLUMNS, availableSplitColumns - MINI_INFO_MIN_COLUMNS))
        : 0;
    const preferredInfoWidth = targetCoverRowsFit
        ? availableSplitColumns - priorityCoverWidth
        : Math.floor(availableSplitColumns * MINI_INFO_RATIO);
    const maxInfoWidth = Math.min(MINI_INFO_MAX_COLUMNS, Math.max(0, availableSplitColumns - MINI_COVER_MIN_COLUMNS));
    const infoWidth = hasArtworkSpace
        ? Math.min(Math.max(preferredInfoWidth, MINI_INFO_MIN_COLUMNS), maxInfoWidth)
        : contentColumns;
    const infoLeftPadding = hasArtworkSpace ? MINI_INFO_LEFT_PADDING : 0;
    const infoInnerWidth = Math.max(0, infoWidth - infoLeftPadding);
    const coverWidth = hasArtworkSpace ? Math.max(0, availableSplitColumns - infoWidth) : 0;
    const infoTop = Math.max(0, Math.floor((contentRows - MINI_INFO_ROWS) / 2));

    return {
        mode,
        contentColumns,
        contentRows,
        infoWidth,
        infoLeftPadding,
        infoTop,
        gap,
        coverWidth,
        progressSlot: {
            row: Math.max(1, Math.min(
                Math.max(1, rows - 1),
                MINI_CONTENT_START_ROW + infoTop + MINI_INFO_ROWS - 2,
            )),
            column: MINI_CONTENT_START_COLUMN + infoLeftPadding,
            width: infoInnerWidth,
        },
        statusIconSlot: {
            row: Math.max(1, Math.min(
                Math.max(1, rows - 1),
                MINI_CONTENT_START_ROW + infoTop + MINI_INFO_ROWS - 1,
            )),
            column: MINI_CONTENT_START_COLUMN + infoLeftPadding,
            width: infoInnerWidth,
        },
    };
}

export function resolveSpotifyImmersiveLayout(size: TerminalSize): SpotifyImmersiveLayout {
    const columns = Math.max(0, size.columns ?? 0);
    const rows = Math.max(0, size.rows ?? 0);
    const topPadding = Math.max(1, Math.floor((Math.max(rows, 1) - SPOTIFY_IMMERSIVE_ROWS) / 2));
    const preferredWidth = Math.min(
        SPOTIFY_PROGRESS_MAX_COLUMNS,
        Math.max(SPOTIFY_PROGRESS_MIN_COLUMNS, Math.max(columns - 16, 0)),
    );
    const width = Math.max(0, Math.min(Math.max(columns - 4, 0), preferredWidth));
    const row = Math.max(1, Math.min(Math.max(1, rows - 1), topPadding + 6));
    const deviceRow = Math.max(1, Math.min(Math.max(1, rows), row + 1));
    const column = Math.max(1, Math.floor((Math.max(columns, width) - width) / 2) + 1);

    return {
        topPadding,
        progressSlot: {
            row,
            column,
            width,
        },
        deviceSlot: {
            row: deviceRow,
            column,
            width,
        },
    };
}

function hasTrackIdentity(player: PlayerState): boolean {
    return Boolean(
        player.session_id
        || player.provider
        || player.source
        || player.name !== '-'
        || player.artist !== '-'
        || player.album !== '-'
    );
}

export function hasActivePlaybackSession(player: PlayerState, _wasSessionActive: boolean): boolean {
    if (player.ended === true) return false;
    if (player.is_playing === true) return true;
    return hasTrackIdentity(player);
}

export function resolveRegionAfterPlayerEvent({
    currentRegion,
    wasSessionActive,
    player,
    spotifyModeEnabled = false,
}: {
    currentRegion: ShellRegion;
    wasSessionActive: boolean;
    player: PlayerState;
    spotifyModeEnabled?: boolean;
}): PlayerRegionTransition {
    const sessionActive = hasActivePlaybackSession(player, wasSessionActive);
    if (!sessionActive) {
        return { region: 'chat', sessionActive: false };
    }
    if (spotifyModeEnabled) {
        return { region: 'spotifyImmersive', sessionActive: true };
    }
    if (!wasSessionActive) {
        return { region: 'miniPlayer', sessionActive: true };
    }
    return { region: currentRegion, sessionActive: true };
}

export function toggleShellRegion(currentRegion: ShellRegion, sessionActive: boolean, spotifyModeEnabled = false): ShellRegion {
    if (!sessionActive) return 'chat';
    if (currentRegion === 'spotifyImmersive') return 'chat';
    if (spotifyModeEnabled && currentRegion === 'chat') return 'spotifyImmersive';
    return currentRegion === 'chat' ? 'miniPlayer' : 'chat';
}

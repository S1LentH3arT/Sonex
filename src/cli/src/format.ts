import stringWidth from 'string-width';

import type { MusicCandidateDisplay } from './types.js';

/**
 * Coordinates the format duration operation for the CLI UI runtime.
 *
 * @param ms Input value used by the format duration operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function formatDuration(ms: number): string {
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = (totalSeconds % 60).toString().padStart(2, "0");
    return `${minutes}:${seconds}`;
}

export function formatMiniTrackSubtitle(artist: string, album: string): string {
    return [artist, album]
        .map((value) => value.trim())
        .filter((value) => value && value !== '-')
        .join('-');
}

const MUSIC_CANDIDATE_ARTIST_WIDTH = 24;
const MUSIC_CANDIDATE_ALBUM_WIDTH = 32;
const ELLIPSIS = "...";

export function fitDisplayWidthWithEllipsis(value: string, width: number): string {
    const normalized = value.trim() || "-";
    if (stringWidth(normalized) <= width) {
        return normalized + " ".repeat(Math.max(0, width - stringWidth(normalized)));
    }

    const contentWidth = Math.max(0, width - stringWidth(ELLIPSIS));
    let rendered = "";
    let renderedWidth = 0;
    for (const char of Array.from(normalized)) {
        const charWidth = stringWidth(char);
        if (renderedWidth + charWidth > contentWidth) break;
        rendered += char;
        renderedWidth += charWidth;
    }

    const result = `${rendered}${ELLIPSIS}`;
    return result + " ".repeat(Math.max(0, width - stringWidth(result)));
}

function truncateDisplayWidthWithEllipsis(value: string, width: number): string {
    const normalized = value.trim() || "-";
    if (width <= 0) return "";
    if (stringWidth(normalized) <= width) return normalized;

    const contentWidth = Math.max(0, width - stringWidth(ELLIPSIS));
    let rendered = "";
    let renderedWidth = 0;
    for (const char of Array.from(normalized)) {
        const charWidth = stringWidth(char);
        if (renderedWidth + charWidth > contentWidth) break;
        rendered += char;
        renderedWidth += charWidth;
    }
    return `${rendered}${ELLIPSIS}`;
}

export function formatMusicCandidateDisplayLabel(
    display: MusicCandidateDisplay,
    rowWidth?: number,
    trailingText?: string | null,
): string {
    const prefix = [
        fitDisplayWidthWithEllipsis(display.artist, MUSIC_CANDIDATE_ARTIST_WIDTH),
        fitDisplayWidthWithEllipsis(display.album, MUSIC_CANDIDATE_ALBUM_WIDTH),
    ].join(" ");
    const title = display.title.trim() || "-";
    if (typeof rowWidth !== "number") {
        return `${prefix} ${title}`;
    }

    const providerText = trailingText?.trim() ?? "";
    if (providerText) {
        const titlePrefix = `${prefix} `;
        const providerMaxWidth = Math.max(0, rowWidth - stringWidth(titlePrefix) - 1);
        const provider = truncateDisplayWidthWithEllipsis(providerText, providerMaxWidth);
        const titleWidth = Math.max(
            0,
            rowWidth - stringWidth(titlePrefix) - stringWidth(provider) - 1,
        );
        const renderedTitle = truncateDisplayWidthWithEllipsis(title, titleWidth);
        const gapWidth = Math.max(
            1,
            rowWidth - stringWidth(titlePrefix) - stringWidth(renderedTitle) - stringWidth(provider),
        );
        return `${titlePrefix}${renderedTitle}${" ".repeat(gapWidth)}${provider}`;
    }

    const titleWidth = Math.max(0, rowWidth - stringWidth(prefix) - 1);
    return `${prefix} ${truncateDisplayWidthWithEllipsis(title, titleWidth)}`;
}

/**
 * Coordinates the build progress bar operation for the CLI UI runtime.
 *
 * @param progressMs Input value used by the build progress bar operation.
 * @param durationMs Input value used by the build progress bar operation.
 * @param width Input value used by the build progress bar operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function buildProgressBar(progressMs: number, durationMs: number, width = 18): string {
    if (durationMs <= 0) return "─".repeat(width);
    const ratio = Math.min(1, Math.max(0, progressMs / durationMs));
    const exact = ratio * width;
    const filled = Math.floor(exact);
    if (filled >= width) return "━".repeat(width);
    const partial = exact - filled >= 0.5 ? "╸" : "";
    return "━".repeat(filled) + partial + "─".repeat(width - filled - partial.length);
}

import type { TrackPanelTrack } from './types.js';
import stringWidth from 'string-width';

const textValue = (value: unknown): string => String(value ?? "").trim();
const TRACK_PANEL_INDEX_WIDTH = 3;
const TRACK_PANEL_ARTIST_WIDTH = 24;
const ELLIPSIS = "...";

const codepoints = (value: string): string[] => Array.from(value);

function fitDisplayWidthWithEllipsis(value: string, width: number): string {
    const normalized = textValue(value) || "-";
    if (stringWidth(normalized) <= width) {
        return normalized + " ".repeat(Math.max(0, width - stringWidth(normalized)));
    }

    const contentWidth = Math.max(0, width - stringWidth(ELLIPSIS));
    let rendered = "";
    let renderedWidth = 0;
    for (const char of codepoints(normalized)) {
        const charWidth = stringWidth(char);
        if (renderedWidth + charWidth > contentWidth) break;
        rendered += char;
        renderedWidth += charWidth;
    }

    const result = `${rendered}${ELLIPSIS}`;
    return result + " ".repeat(Math.max(0, width - stringWidth(result)));
}

function truncateDisplayWidthWithEllipsis(value: string, width: number): string {
    const normalized = textValue(value) || "-";
    if (width <= 0) return "";
    if (stringWidth(normalized) <= width) return normalized;

    const contentWidth = Math.max(0, width - stringWidth(ELLIPSIS));
    let rendered = "";
    let renderedWidth = 0;
    for (const char of codepoints(normalized)) {
        const charWidth = stringWidth(char);
        if (renderedWidth + charWidth > contentWidth) break;
        rendered += char;
        renderedWidth += charWidth;
    }
    return `${rendered}${ELLIPSIS}`;
}

function padStartDisplayWidth(value: string, width: number): string {
    const normalized = textValue(value) || "-";
    const renderedWidth = stringWidth(normalized);
    return " ".repeat(Math.max(0, width - renderedWidth)) + normalized;
}

export function formatTrackPanelIndex(track: TrackPanelTrack): string {
    const index = padStartDisplayWidth(track.index, TRACK_PANEL_INDEX_WIDTH);
    return track.queued ? `✓${index}` : ` ${index}`;
}

export function formatTrackPanelLine(track: TrackPanelTrack, rowWidth: number): string {
    const prefix = [
        formatTrackPanelIndex(track),
        fitDisplayWidthWithEllipsis(track.artist, TRACK_PANEL_ARTIST_WIDTH),
    ].join(" ");
    const titleWidth = Math.max(0, rowWidth - stringWidth(prefix) - 1);
    return `${prefix} ${truncateDisplayWidthWithEllipsis(track.title, titleWidth)}`;
}

export function trackPanelTrackKey(track: TrackPanelTrack): string {
    for (const field of [
        "cache_id",
        "uri",
        "spotify_url",
        "requires_resolution",
        "youtube_url",
        "url",
        "stream_url",
        "audio_path",
        "file_path",
        "path",
        "id",
    ] as const) {
        const value = textValue(track[field]);
        if (value) return `${field}:${value}`;
    }
    const name = textValue(track.name || track.title);
    const artist = textValue(track.artist);
    const album = textValue(track.album);
    const duration = Number(track.duration_ms || 0);
    if (!name) return "";
    if (artist || album || duration || textValue(track.provider || track.source) === "local") {
        return `text:${name.toLowerCase()}|${artist.toLowerCase()}|${album.toLowerCase()}|${duration}`;
    }
    return "";
}

export function markQueuedTracks(tracks: TrackPanelTrack[], queuedTracks: TrackPanelTrack[]): TrackPanelTrack[] {
    const queuedKeys = new Set(queuedTracks.map(trackPanelTrackKey).filter(Boolean));
    return tracks.map((track) => {
        const key = trackPanelTrackKey(track);
        return { ...track, queued: Boolean(key && queuedKeys.has(key)) };
    });
}

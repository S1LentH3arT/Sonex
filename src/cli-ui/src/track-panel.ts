import type { TrackPanelTrack } from './types.js';

const textValue = (value: unknown): string => String(value ?? "").trim();

export function trackPanelTrackKey(track: TrackPanelTrack): string {
    for (const field of [
        "cache_id",
        "uri",
        "spotify_url",
        "apple_music_url",
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

import assert from 'node:assert/strict';
import { markQueuedTracks, trackPanelTrackKey } from '../src/track-panel.js';
import type { TrackPanelTrack } from '../src/types.js';

const playlistTracks: TrackPanelTrack[] = [
    {
        index: "01",
        title: "Queued Song",
        artist: "Artist",
        duration: "02:03",
        uri: "spotify:track:queued",
    },
    {
        index: "02",
        title: "Other Song",
        artist: "Artist",
        duration: "03:04",
        uri: "spotify:track:other",
    },
];

assert.equal(trackPanelTrackKey(playlistTracks[0]!), "uri:spotify:track:queued");

const markedTracks = markQueuedTracks(playlistTracks, [
    {
        index: "01",
        title: "Queued Song",
        artist: "Artist",
        duration: "02:03",
        uri: "spotify:track:queued",
    },
]);

assert.equal(markedTracks[0]?.queued, true);
assert.equal(markedTracks[1]?.queued, false);
assert.equal(playlistTracks[0]?.queued, undefined);

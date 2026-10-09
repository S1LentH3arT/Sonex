import assert from 'node:assert/strict';
import stringWidth from 'string-width';

import { formatTrackPanelLine, markQueuedTracks, trackPanelTrackKey } from '../src/track-panel.js';
import type { TrackPanelTrack } from '../src/types.js';

const titleStartWidth = (label: string, title: string): number => (
    stringWidth(label.slice(0, label.indexOf(title)))
);

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

const formattedShortTrack = formatTrackPanelLine({
    index: "01",
    title: "青花瓷",
    artist: "周杰伦",
    duration: "03:58",
}, 96);

assert.equal(formattedShortTrack, `  01 周杰伦                   青花瓷`);
assert.equal(titleStartWidth(formattedShortTrack, "青花瓷"), 30);

const formattedEnglishArtist = formatTrackPanelLine({
    index: "01",
    title: "Willow",
    artist: "Taylor Swift",
    duration: "03:58",
}, 96);

assert.equal(titleStartWidth(formattedEnglishArtist, "Willow"), 30);

const formattedLongArtist = formatTrackPanelLine({
    index: "123",
    title: "Short title",
    artist: "abcdefghijklmnopqrstuvwxy",
    duration: "03:58",
}, 96);

assert.equal(formattedLongArtist, ` 123 abcdefghijklmnopqrstu... Short title`);

const formattedLongTitle = formatTrackPanelLine({
    index: "7",
    title: "This Song Title Is Too Long For The Track Panel Row",
    artist: "Taylor Swift",
    duration: "03:58",
}, 42);

assert.equal(stringWidth(formattedLongTitle), 42);
assert.equal(formattedLongTitle, "   7 Taylor Swift             This Song...");

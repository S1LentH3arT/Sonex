import assert from 'node:assert/strict';
import stringWidth from 'string-width';

import { formatMusicCandidateDisplayLabel } from '../src/format.js';
import type { MusicCandidateDisplay } from '../src/types.js';

const titleStartWidth = (label: string, title: string): number => (
    stringWidth(label.slice(0, label.indexOf(title)))
);

const englishCandidate: MusicCandidateDisplay = {
    kind: 'music_candidate',
    artist: 'Taylor Swift',
    album: 'Evermore',
    title: 'Willow',
};

const chineseCandidate: MusicCandidateDisplay = {
    kind: 'music_candidate',
    artist: '周杰伦',
    album: '我很忙',
    title: '青花瓷',
};

const englishLabel = formatMusicCandidateDisplayLabel(englishCandidate);
const chineseLabel = formatMusicCandidateDisplayLabel(chineseCandidate);

assert.equal(titleStartWidth(englishLabel, englishCandidate.title), 50);
assert.equal(titleStartWidth(chineseLabel, chineseCandidate.title), 50);

const longChineseLabel = formatMusicCandidateDisplayLabel({
    kind: 'music_candidate',
    artist: '周杰伦周杰伦周杰伦周杰伦周杰伦',
    album: '我很忙我很忙我很忙我很忙',
    title: '青花瓷',
});

assert.match(longChineseLabel, /\.\.\./);
assert.equal(titleStartWidth(longChineseLabel, '青花瓷'), 50);

const wideAlbumLabel = formatMusicCandidateDisplayLabel({
    kind: 'music_candidate',
    artist: 'Taylor Swift',
    album: 'The Tortured Poets Department',
    title: 'Fortnight',
});

assert.equal(titleStartWidth(wideAlbumLabel, 'Fortnight'), 50);

const truncatedTitleLabel = formatMusicCandidateDisplayLabel({
    kind: 'music_candidate',
    artist: 'Taylor Swift',
    album: 'The Tortured Poets Department',
    title: 'This Song Title Is Too Long For The Current Candidate Row',
}, 64);

assert.equal(stringWidth(truncatedTitleLabel), 64);
assert.match(truncatedTitleLabel, /\.\.\.$/);

const providerAlignedLabel = formatMusicCandidateDisplayLabel(englishCandidate, 94, 'iTunes');

assert.equal(stringWidth(providerAlignedLabel), 94);
assert.match(providerAlignedLabel, /Willow\s{2,}iTunes$/);

const providerAfterLongTitleLabel = formatMusicCandidateDisplayLabel({
    kind: 'music_candidate',
    artist: 'Taylor Swift',
    album: 'The Tortured Poets Department',
    title: 'This Song Title Is Too Long For The Current Candidate Row',
}, 94, 'iTunes');

assert.equal(stringWidth(providerAfterLongTitleLabel), 94);
assert.match(providerAfterLongTitleLabel, /\.\.\. iTunes$/);

const providerAfterChineseTitleLabel = formatMusicCandidateDisplayLabel({
    kind: 'music_candidate',
    artist: '周杰伦',
    album: '我很忙',
    title: '这是一首长度很长很长需要按照终端显示宽度截断的中文歌曲名称',
}, 94, 'iTunes');

assert.equal(stringWidth(providerAfterChineseTitleLabel), 94);
assert.match(providerAfterChineseTitleLabel, /\.\.\. iTunes$/);

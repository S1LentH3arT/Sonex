import assert from 'node:assert/strict';

import {
    fitPanelSegments,
    PANEL_BACKGROUND,
    PANEL_PRIMARY,
    PANEL_SECONDARY,
    PANEL_TITLE,
    panelContentWidth,
    resolvePanelChoiceSegments,
    type PanelChoiceItem,
    withPanelBackground,
} from '../src/panel-frame.js';
import { withTrueColorBackground } from '../src/terminal-frame-writer.js';

assert.equal(PANEL_BACKGROUND, '#48273e');
assert.equal(PANEL_TITLE, '#c8a6ff');
assert.equal(PANEL_PRIMARY, '#fff4f6');
assert.equal(PANEL_SECONDARY, '#808791');
assert.equal(
    withPanelBackground('provider input row'),
    withTrueColorBackground('provider input row', '#48273e'),
);
assert.equal(
    withPanelBackground('panel row'),
    '\u001B[48;2;72;39;62mpanel row\u001B[49m',
);

assert.equal(panelContentWidth(80), 78);
assert.equal(panelContentWidth(74, 2), 70);
assert.equal(panelContentWidth(2), 1);

assert.deepEqual(
    fitPanelSegments([
        { text: '歌手 ', color: PANEL_PRIMARY },
        { text: 'Album', color: PANEL_SECONDARY },
    ], 7),
    [
        { text: '歌手 ', color: PANEL_PRIMARY },
        { text: 'Al', color: PANEL_SECONDARY },
    ],
);

const choice: PanelChoiceItem = {
    key: 'choice',
    segments: [
        { text: 'Song', color: PANEL_PRIMARY },
        { text: '  Artist', color: PANEL_SECONDARY },
    ],
};

assert.deepEqual(resolvePanelChoiceSegments(choice, true, false), [{
    text: 'Song  Artist',
    color: '#3b82f6',
    bold: true,
}]);
assert.deepEqual(resolvePanelChoiceSegments(choice, true, true), [{
    text: 'Song  Artist',
    color: '#1db954',
    bold: true,
}]);
assert.deepEqual(resolvePanelChoiceSegments({ ...choice, selectedColor: '#ef4444' }, true, false), [{
    text: 'Song  Artist',
    color: '#ef4444',
    bold: true,
}]);
assert.deepEqual(resolvePanelChoiceSegments(choice, false, false), choice.segments);
assert.equal(resolvePanelChoiceSegments({ ...choice, unselectedBold: true }, false, false).every((segment) => segment.bold), true);

const statusChoice: PanelChoiceItem = {
    key: 'provider',
    segments: [
        { text: '• ', color: PANEL_SECONDARY, preserveColorWhenSelected: true },
        { text: 'OpenAI — Not connected', color: PANEL_PRIMARY },
    ],
};
assert.deepEqual(resolvePanelChoiceSegments(statusChoice, true, false), [
    { text: '• ', color: PANEL_SECONDARY, preserveColorWhenSelected: true, bold: true },
    { text: 'OpenAI — Not connected', color: '#3b82f6', bold: true },
]);

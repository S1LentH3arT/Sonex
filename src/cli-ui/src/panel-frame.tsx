import React, { type ReactNode } from 'react';
import { Box, Text, Transform } from 'ink';
import stringWidth from 'string-width';

import { wrapChatMessageContent } from './chat-message.js';
import { BORDER_BLUE, SPOTIFY_GREEN } from './constants.js';
import { withTrueColorBackground } from './terminal-frame-writer.js';

export const PANEL_BACKGROUND = "#48273e";
export const PANEL_TITLE = "#c8a6ff";
export const PANEL_PRIMARY = "#fff4f6";
export const PANEL_SECONDARY = "#808791";

export const withPanelBackground = (value: string): string => (
    withTrueColorBackground(value, PANEL_BACKGROUND)
);

export type PanelRowSegment = {
    text: string;
    color?: string;
    bold?: boolean;
};

export type PanelChoiceItem = {
    key: string;
    segments: PanelRowSegment[];
    unselectedBold?: boolean;
    gapBefore?: boolean;
};

const boundedPanelWidth = (width: number): number => Math.max(3, Math.floor(width));

export const panelContentWidth = (width: number, paddingX = 1): number => (
    Math.max(1, boundedPanelWidth(width) - Math.max(0, Math.floor(paddingX)) * 2)
);

export const fitPanelSegments = (
    segments: PanelRowSegment[],
    width: number,
): PanelRowSegment[] => {
    const targetWidth = Math.max(0, Math.floor(width));
    const fitted: PanelRowSegment[] = [];
    let usedWidth = 0;

    for (const segment of segments) {
        let text = "";
        for (const character of Array.from(segment.text)) {
            const characterWidth = stringWidth(character);
            if (usedWidth + characterWidth > targetWidth) break;
            text += character;
            usedWidth += characterWidth;
        }
        if (text) fitted.push({ ...segment, text });
        if (usedWidth >= targetWidth) break;
    }

    return fitted;
};

export const resolvePanelChoiceSegments = (
    item: PanelChoiceItem,
    selected: boolean,
    spotifyTheme: boolean,
): PanelRowSegment[] => {
    if (!selected) {
        return item.unselectedBold
            ? item.segments.map((segment) => ({ ...segment, bold: true }))
            : item.segments;
    }

    return [{
        text: item.segments.map((segment) => segment.text).join(""),
        color: spotifyTheme ? SPOTIFY_GREEN : BORDER_BLUE,
        bold: true,
    }];
};

export const PanelEmptyRow = ({ width }: { width: number }) => (
    <Text>
        <Transform transform={withPanelBackground}>
            <Text>{" ".repeat(boundedPanelWidth(width))}</Text>
        </Transform>
    </Text>
);

export const PanelRow = ({
    width,
    segments,
    paddingX = 1,
}: {
    width: number;
    segments: PanelRowSegment[];
    paddingX?: number;
}) => {
    const boundedWidth = boundedPanelWidth(width);
    const boundedPadding = Math.max(
        0,
        Math.min(Math.floor(paddingX), Math.floor((boundedWidth - 1) / 2)),
    );
    const contentWidth = panelContentWidth(boundedWidth, boundedPadding);
    const fittedSegments = fitPanelSegments(segments, contentWidth);
    const fittedWidth = fittedSegments.reduce((total, segment) => total + stringWidth(segment.text), 0);
    const rightPadding = Math.max(
        boundedPadding,
        boundedWidth - boundedPadding - fittedWidth,
    );

    return (
        <Text>
            <Transform transform={withPanelBackground}>
                <Text>
                    {" ".repeat(boundedPadding)}
                    {fittedSegments.map((segment, index) => (
                        <Text
                            key={`${index}-${segment.text}`}
                            color={segment.color ?? PANEL_PRIMARY}
                            bold={segment.bold}
                        >
                            {segment.text}
                        </Text>
                    ))}
                    {" ".repeat(rightPadding)}
                </Text>
            </Transform>
        </Text>
    );
};

export const PanelChoiceList = ({
    items,
    selectedIndex,
    width,
    paddingX = 1,
    spotifyTheme = false,
    visibleLimit,
}: {
    items: PanelChoiceItem[];
    selectedIndex: number;
    width: number;
    paddingX?: number;
    spotifyTheme?: boolean;
    visibleLimit?: number;
}) => {
    if (items.length === 0) return null;

    const boundedIndex = selectedIndex < 0
        ? -1
        : Math.min(selectedIndex, items.length - 1);
    const limit = Math.max(1, Math.min(visibleLimit ?? items.length, items.length));
    const maxStart = Math.max(0, items.length - limit);
    const startIndex = Math.min(Math.max(0, boundedIndex - limit + 1), maxStart);
    const visibleItems = items.slice(startIndex, startIndex + limit);

    return (
        <Box flexDirection="column">
            {visibleItems.map((item, index) => {
                const selected = startIndex + index === boundedIndex;
                return (
                    <React.Fragment key={item.key}>
                        {item.gapBefore ? <PanelEmptyRow width={width} /> : null}
                        <PanelRow
                            width={width}
                            paddingX={paddingX}
                            segments={resolvePanelChoiceSegments(item, selected, spotifyTheme)}
                        />
                    </React.Fragment>
                );
            })}
        </Box>
    );
};

export const PanelFrame = ({
    width,
    title,
    hint = null,
    hintColor = PANEL_SECONDARY,
    paddingX = 1,
    children,
}: {
    width: number;
    title: string;
    hint?: string | null;
    hintColor?: string;
    paddingX?: number;
    children?: ReactNode;
}) => {
    const boundedWidth = boundedPanelWidth(width);
    const contentWidth = panelContentWidth(boundedWidth, paddingX);
    const titleRows = wrapChatMessageContent(title, contentWidth);
    const hintRows = hint ? wrapChatMessageContent(hint, contentWidth) : [];

    return (
        <Box width={boundedWidth} flexDirection="column" flexShrink={0}>
            <PanelEmptyRow width={boundedWidth} />
            {titleRows.map((row, index) => (
                <PanelRow
                    key={`panel-title-${index}`}
                    width={boundedWidth}
                    paddingX={paddingX}
                    segments={[{ text: row, color: PANEL_TITLE, bold: true }]}
                />
            ))}
            {hintRows.map((row, index) => (
                <PanelRow
                    key={`panel-hint-${index}`}
                    width={boundedWidth}
                    paddingX={paddingX}
                    segments={[{ text: row, color: hintColor }]}
                />
            ))}
            <PanelEmptyRow width={boundedWidth} />
            {children}
            <PanelEmptyRow width={boundedWidth} />
        </Box>
    );
};

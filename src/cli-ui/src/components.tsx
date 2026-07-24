import React from 'react';
import { Box, Text, Transform, measureElement } from 'ink';
import TextInput from 'ink-text-input';
import stringWidth from 'string-width';
import { APP_VERSION, BORDER_BLUE, BORDER_BLUE_SOFT, FALLBACK_MODEL_NAME, MAX_VISIBLE_MODEL_CHOICES, MAX_VISIBLE_SLASH_COMMANDS, SONEX_MASCOT, SONEX_MASCOT_MICRO } from './constants.js';
import { HELP_PANEL_VISIBLE_COMMANDS, helpPanelCommands, visibleCommandWindow } from './command-panel.js';
import { getVisibleConfirmChoices } from './confirm-choice.js';
import { buildProgressBar, formatDuration, formatMiniTrackSubtitle, formatMusicCandidateDisplayLabel } from './format.js';
import { getVisibleChatWindow } from './chat-window.js';
import { isHttpCoverSource, useCoverArt } from './hooks.js';
import { hideInputCursor } from './input-cursor.js';
import { languageLabel, t } from './i18n.js';
import { coverVisualFromSource, type CoverVisualModel } from './cover-visual.js';
import { renderCoverPatternHalfBlocks, resolveCoverPatternDisplay, type CoverPatternPayload, type CoverPatternVariant, type TerminalSpace } from './cover-pattern.js';
import { resolveMiniPlayerLayout, type ChatHeaderVariant, type MiniPlayerLayout, type ShellRegion, type SpotifyImmersiveLayout } from './layout.js';
import { buildPlaybackStatusIconLine } from './mini-progress-writer.js';
import { formatTrackPanelLine } from './track-panel.js';
import type { ActivityItem, ActivityKind, AuthMethodChoice, AuthRuntimeState, AuthSetupState, ChatBubbleProps, ChatItem, ConfirmChoice, ConfirmState, HelpPanelState, LanguagePanelState, LoginScreenProps, PlayerPaneVariant, PlayerState, PromptInputProps, SlashCommandSuggestion, SpotifyModeState, SpotifySetupState, TrackPanelState, TrackPanelTrack, TrackSummary, UiLanguage } from './types.js';

const Mascot = () => {
    return (
        <Box width={16} flexDirection="column" marginRight={3}>
            {SONEX_MASCOT.map((row, rowIndex) => (
                <Text key={rowIndex}>
                    {row.map((segment, segmentIndex) => (
                        <Text key={segmentIndex} color={segment.fg} backgroundColor={segment.bg}>
                            {segment.text}
                        </Text>
                    ))}
                </Text>
            ))}
        </Box>
    );
};

const MiniMascotStatus = () => {
    return (
        <Box height={1} flexShrink={0} paddingLeft={1} paddingRight={1} flexDirection="column" alignItems="flex-start">
            {SONEX_MASCOT_MICRO.map((row, rowIndex) => (
                <Text key={rowIndex}>
                    {row.map((segment, segmentIndex) => (
                        <Text key={segmentIndex} color={segment.fg} backgroundColor={segment.bg}>
                            {segment.text}
                        </Text>
                    ))}
                </Text>
            ))}
        </Box>
    );
};

export const formatAuthLabel = (state: AuthRuntimeState): string => {
    if (state.credential_source === "local" || state.auth_type === "local") {
        return "local";
    }
    if (!state.ready) {
        return "login required";
    }
    if (state.auth_type === "api_key") {
        return "API billing";
    }
    if (state.auth_type === "oauth") {
        return "OAuth";
    }
    return state.auth_type || state.credential_source || "auth";
};

export const HeaderFrame = ({ authState, variant, language = "en" }: { authState: AuthRuntimeState; variant: ChatHeaderVariant; language?: UiLanguage }) => {
    const identity = `${authState.model || authState.provider || FALLBACK_MODEL_NAME} • ${formatAuthLabel(authState)}`;
    if (variant === 'compact') {
        return (
            <Box width="100%" height={5} paddingX={1} borderStyle="round" borderColor="#808791" flexDirection="column">
                <Text><Text bold color="#fff4f6">Sonex CLI</Text> <Text bold color={BORDER_BLUE}>v{APP_VERSION}</Text></Text>
                <Box height={1} />
                <Text color="#d8bcc7" wrap="truncate-end">{identity}</Text>
            </Box>
        );
    }

    return (
        <Box width="100%" minHeight={9} paddingX={1} borderStyle="round" borderColor="#808791">
            <Mascot />
            <Box flexDirection="column" justifyContent="flex-start">
                <Text><Text bold color="#fff4f6">Sonex CLI</Text> <Text bold color={BORDER_BLUE}>v{APP_VERSION}</Text></Text>
                <Box height={1} />
                <Text color="#d8bcc7">{identity}</Text>
                <Text color="#bf98a7">~/dev/sonex</Text>
            </Box>
        </Box>
    );
};

export const isGenericAuthSetup = (setup: AuthSetupState): boolean => {
    if (!setup?.active) return false;
    return setup.provider !== "apple_music";
};

const LoginChoiceList = ({ choices, selectedIndex, visibleLimit }: {
    choices: AuthMethodChoice[];
    selectedIndex: number;
    visibleLimit?: number;
}) => {
    const boundedIndex = Math.min(Math.max(selectedIndex, 0), Math.max(0, choices.length - 1));
    const limit = Math.min(visibleLimit ?? choices.length, choices.length);
    const maxStart = Math.max(0, choices.length - limit);
    const startIndex = Math.min(Math.max(0, boundedIndex - limit + 1), maxStart);
    const visibleChoices = choices.slice(startIndex, startIndex + limit);

    return (
        <Box flexDirection="column" marginTop={1}>
            {visibleChoices.map((choice, index) => {
                const absoluteIndex = startIndex + index;
                return (
                    <Text key={choice.value} color={absoluteIndex === boundedIndex ? "#fff4f6" : "#bf98a7"}>
                        <Text color={absoluteIndex === boundedIndex ? BORDER_BLUE_SOFT : "#7f5d6b"}>
                            {absoluteIndex === boundedIndex ? "> " : "  "}
                        </Text>
                        {choice.label}
                        <Text color="#7f5d6b">  </Text>
                        <Text color="#9d7787">{choice.provider ?? choice.value}</Text>
                    </Text>
                );
            })}
        </Box>
    );
};

export const LoginScreen = ({
    authSetup,
    selectedIndex,
    apiKeyInput,
    setApiKeyInput,
    onApiKeySubmit,
    language = "en",
}: LoginScreenProps & { language?: UiLanguage }) => {
    if (!authSetup) return null;

    const providerChoices = authSetup.providers ?? [];
    const methodChoices = authSetup.methods ?? [];
    const isProviderStep = authSetup.step === "provider";
    const isMethodStep = authSetup.step === "method";
    const modelChoices = authSetup.models ?? [];
    const isApiKeyStep = authSetup.step === "api_key";
    const isModelStep = authSetup.step === "model";
    const isOauthWait = authSetup.step === "oauth_wait";
    const choices = isProviderStep ? providerChoices : isMethodStep ? methodChoices : isModelStep ? modelChoices : [];
    const displayMessage = isProviderStep
        ? t(language, "login.warmup")
        : authSetup.message;

    return (
        <Box width={74} minHeight={18} paddingX={1} paddingY={1} borderStyle="single" borderColor={BORDER_BLUE} flexDirection="column">
            <Box flexDirection="column" marginTop={1} paddingX={1}>
                <Text color="#fff4f6">{authSetup.title}</Text>
                <Text color="#bf98a7">{displayMessage}</Text>

                {(isProviderStep || isMethodStep || isModelStep) ? (
                    <>
                        <LoginChoiceList
                            choices={choices}
                            selectedIndex={selectedIndex}
                            visibleLimit={isModelStep ? MAX_VISIBLE_MODEL_CHOICES : undefined}
                        />
                        <Text color="#7f5d6b">{t(language, "login.continue")}</Text>
                    </>
                ) : null}

                {isApiKeyStep ? (
                    <Box flexDirection="column" marginTop={1}>
                        <Text color="#9d7787">{authSetup.prompt ?? "API key"}</Text>
                        <Box>
                            <Text color="#7f5d6b">{"> "}</Text>
                            <PromptInput
                                input={apiKeyInput}
                                setInput={setApiKeyInput}
                                onSubmit={onApiKeySubmit}
                                focus={true}
                                placeholder={authSetup.prompt ?? "API key"}
                                mask="*"
                            />
                        </Box>
                    </Box>
                ) : null}

                {isOauthWait ? (
                    <Box flexDirection="column" marginTop={1}>
                        <Text color={BORDER_BLUE_SOFT}>{t(language, "auth.oauth.waiting")}</Text>
                        <Text color="#7f5d6b">{t(language, "auth.oauth.return")}</Text>
                    </Box>
                ) : null}
            </Box>
        </Box>
    );
};

const INPUT_CURSOR_BLINK_INTERVAL_MS = 500;

const PromptInput = ({ input, setInput, onSubmit, focus, placeholder, mask, inputRevision }: PromptInputProps) => {
    const [cursorVisible, setCursorVisible] = React.useState(true);

    React.useEffect(() => {
        setCursorVisible(true);
        if (!focus) return;

        const timer = setInterval(
            () => setCursorVisible((visible) => !visible),
            INPUT_CURSOR_BLINK_INTERVAL_MS,
        );
        return () => clearInterval(timer);
    }, [focus, input, inputRevision]);

    return (
        <Transform transform={(output) => cursorVisible ? output : hideInputCursor(output)}>
            <TextInput
                key={inputRevision}
                value={input}
                onChange={setInput}
                onSubmit={onSubmit}
                focus={focus}
                placeholder={placeholder}
                mask={mask}
            />
        </Transform>
    );
};

type ChoicePanelRow = {
    key: string;
    label: string;
    description?: string | null;
    display?: ConfirmChoice["display"];
    labelWidth?: number;
};

const COMMAND_LIST_LABEL_WIDTH = 12;
const CONFIRM_CHOICE_LABEL_WIDTH = 18;
const CONFIRM_CHOICE_ROW_LABEL_WIDTH = 94;
const MODEL_PANEL_LABEL_WIDTH = 20;
const PLAYLIST_BROWSE_NAME_WIDTH = 32;
const SPOTIFY_GREEN = "#1db954";
const SPOTIFY_SELECTED_TEXT = "#06140c";
const TRACK_PANEL_ROW_WIDTH = 96;

const truncateDisplayWidth = (value: string, width: number): string => {
    const normalized = value.trim() || "-";
    let rendered = "";
    for (const char of normalized) {
        if (stringWidth(rendered + char) > width) break;
        rendered += char;
    }
    return rendered || "-";
};

const fitDisplayWidth = (value: string, width: number): string => {
    const rendered = truncateDisplayWidth(value, width);
    return rendered + " ".repeat(Math.max(0, width - stringWidth(rendered)));
};

const formatCommandListLabel = (command: Pick<SlashCommandSuggestion, "name">): string => (
    `/${command.name}`.slice(0, COMMAND_LIST_LABEL_WIDTH).padEnd(COMMAND_LIST_LABEL_WIDTH, " ")
);

const modelIdFromChoice = (model: AuthMethodChoice): string => {
    const valueParts = model.value.split("::");
    return valueParts.length > 1 ? valueParts.slice(1).join("::") : model.label;
};

const formatModelPanelLabel = (model: AuthMethodChoice): string => (
    modelIdFromChoice(model).padEnd(MODEL_PANEL_LABEL_WIDTH, " ")
);

const formatPlaylistBrowseName = (label: string): string => (
    fitDisplayWidth(label, PLAYLIST_BROWSE_NAME_WIDTH)
);

const playlistBrowseTrackCount = (choice: ConfirmChoice): string => {
    const numericCount = typeof choice.track_count === "number"
        ? choice.track_count
        : Number.parseInt(choice.description ?? "", 10);
    const count = Number.isFinite(numericCount) && numericCount > 0 ? Math.trunc(numericCount) : 0;
    return `${count} track${count === 1 ? "" : "s"}`;
};

const formatChoicePanelLabel = (row: ChoicePanelRow): string => (
    row.display?.kind === "music_candidate"
        ? formatMusicCandidateDisplayLabel(row.display, CONFIRM_CHOICE_ROW_LABEL_WIDTH, row.description)
        : row.labelWidth
        ? row.label + " ".repeat(Math.max(0, row.labelWidth - stringWidth(row.label)))
        : row.label
);

const ChoicePanel = ({ rows, selectedIndex, visibleLimit, selectedBackgroundColor }: {
    rows: ChoicePanelRow[];
    selectedIndex: number;
    visibleLimit?: number;
    selectedBackgroundColor?: string;
}) => {
    if (rows.length === 0) return null;
    const { items: visibleRows, boundedIndex, startIndex } = visibleCommandWindow(
        rows,
        selectedIndex,
        visibleLimit ?? rows.length,
    );

    return (
        <Box flexDirection="column" marginTop={1}>
            {visibleRows.map((row, index) => {
                const absoluteIndex = startIndex + index;
                const selected = absoluteIndex === boundedIndex;
                const rowBackgroundColor = selected ? selectedBackgroundColor : undefined;
                const rowColor = selectedBackgroundColor && selected ? "#06140c" : selected ? BORDER_BLUE : "#fff4f6";
                return (
                    <Text key={row.key} backgroundColor={rowBackgroundColor}>
                        <Text color={rowColor} backgroundColor={rowBackgroundColor}>{selected ? "> " : "  "}</Text>
                        <Text color={rowColor} backgroundColor={rowBackgroundColor} wrap="truncate-end">{formatChoicePanelLabel(row)}</Text>
                        {row.description && row.display?.kind !== "music_candidate" ? (
                            <>
                                <Text color={rowColor} backgroundColor={rowBackgroundColor}>{row.description}</Text>
                            </>
                        ) : null}
                    </Text>
                );
            })}
        </Box>
    );
};

const SlashCommandList = ({ suggestions, selectedIndex, spotifyTheme = false }: {
    suggestions: SlashCommandSuggestion[];
    selectedIndex: number;
    spotifyTheme?: boolean;
}) => {
    if (suggestions.length === 0) return null;

    const { items: visibleSuggestions, boundedIndex, startIndex } = visibleCommandWindow(
        suggestions,
        selectedIndex,
        MAX_VISIBLE_SLASH_COMMANDS,
    );

    return (
        <Box flexDirection="column">
            {visibleSuggestions.map((command, index) => {
                const absoluteIndex = startIndex + index;
                const selected = absoluteIndex === boundedIndex;
                const commandColor = selected ? (spotifyTheme ? SPOTIFY_GREEN : BORDER_BLUE) : "#fff4f6";
                const descriptionColor = selected ? commandColor : "#808791";
                return (
                    <Text key={command.name} color={commandColor} bold={selected} wrap="truncate-end">
                        <Text>{formatCommandListLabel(command)}</Text>
                        <Text color={descriptionColor}>{command.description}</Text>
                    </Text>
                );
            })}
        </Box>
    );
};

const HelpPanel = ({ panel, selectedIndex, language = "en" }: { panel: HelpPanelState; selectedIndex: number; language?: UiLanguage }) => {
    if (!panel) return null;
    const commands = helpPanelCommands(panel.commands);
    const { items: visibleCommands, boundedIndex, startIndex } = visibleCommandWindow(
        commands,
        selectedIndex,
        HELP_PANEL_VISIBLE_COMMANDS,
    );

    return (
        <Box flexDirection="column" paddingX={1} paddingBottom={1} borderStyle="single" borderColor={BORDER_BLUE}>
            <Text>
                <Text bold color="#fff4f6">{panel.title}</Text>
                <Text color="#7f5d6b"> - </Text>
                <Text color="#9d7787">{panel.hint}</Text>
            </Text>
            {panel.commands.length === 0 ? (
                <Text color="#7f5d6b">{t(language, "help.empty")}</Text>
            ) : (
                <Box flexDirection="column" marginTop={1}>
                    {visibleCommands.map((command, index) => {
                        const absoluteIndex = startIndex + index;
                        const commandColor = absoluteIndex === boundedIndex ? BORDER_BLUE : "#fff4f6";
                        return (
                            <Text key={command.name}>
                                <Text color={commandColor}>{absoluteIndex === boundedIndex ? "> " : "  "}</Text>
                                <Text color={commandColor}>{formatCommandListLabel(command)}</Text>
                                <Text color={commandColor}>{command.description}</Text>
                            </Text>
                        );
                    })}
                </Box>
            )}
        </Box>
    );
};

const ChatBubble = ({ role, content, theme = null }: ChatBubbleProps) => {
    const isUser = role === "user";
    const color = theme === "muted" && !isUser ? "#9ca3af" : theme === "spotify" && !isUser ? SPOTIFY_GREEN : isUser ? "#fff6f8" : "#f6e9ee";
    const borderLeftColor = theme === "muted" && !isUser ? "#6b7280" : theme === "spotify" && !isUser ? SPOTIFY_GREEN : isUser ? BORDER_BLUE : BORDER_BLUE_SOFT;

    return (
        <Box paddingX={2} marginBottom={1} borderStyle="single" borderTop={false} borderRight={false}
            borderBottom={false} borderLeft={true} borderColor={borderLeftColor} flexDirection="column" width="100%">
            <Text color={color}>{content}</Text>
        </Box>
    );
};

const ChatPane = ({ items, scrollOffset, onMaxScrollOffsetChange, fill = false, language = "en" }: {
    items: ChatItem[];
    scrollOffset: number;
    onMaxScrollOffsetChange: (value: number) => void;
    fill?: boolean;
    language?: UiLanguage;
}) => {
    const containerRef = React.useRef<any>(null);
    const [viewportSize, setViewportSize] = React.useState({ width: 68, height: 12 });
    const wrapWidth = Math.max(1, viewportSize.width - 7);
    const visibleWindow = React.useMemo(
        () => getVisibleChatWindow(items, viewportSize.height, scrollOffset, wrapWidth),
        [items, scrollOffset, viewportSize.height, wrapWidth],
    );

    React.useEffect(() => {
        if (!containerRef.current) return;
        const { width, height } = measureElement(containerRef.current);
        if (width > 0 && height > 0 && (width !== viewportSize.width || height !== viewportSize.height)) {
            setViewportSize({ width, height });
        }
    });

    React.useEffect(() => {
        onMaxScrollOffsetChange(visibleWindow.maxScrollOffset);
    }, [onMaxScrollOffsetChange, visibleWindow.maxScrollOffset]);

    return (
        <Box ref={containerRef} flexDirection="column" flexGrow={fill ? 1 : 0} flexShrink={1} minHeight={0} overflowY="hidden" paddingX={1}>
            <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} overflowY="hidden">
                {items.length === 0 ? (
                    <Text color="#7f5d6b">{t(language, "chat.empty")}</Text>
                ) : (
                    <>
                        {visibleWindow.hasHiddenAbove ? <Text color="#7f5d6b">{t(language, "chat.hiddenAbove")}</Text> : null}
                        {visibleWindow.items.map((chat, idx) => (
                            <ChatBubble key={`${items.indexOf(chat)}_${idx}`} role={chat.role} content={chat.content} theme={chat.theme} />
                        ))}
                        {visibleWindow.hasHiddenBelow ? <Text color="#7f5d6b">{t(language, "chat.hiddenBelow")}</Text> : null}
                    </>
                )}
            </Box>
        </Box>
    );
};

const localizeTrackPanelTitle = (panel: NonNullable<TrackPanelState>, language: UiLanguage): string => {
    if (panel.panel === "queue") return t(language, "trackPanel.queue");
    const playlistPrefix = "Playlist:";
    if (panel.title.startsWith(playlistPrefix)) {
        const playlistName = panel.title.slice(playlistPrefix.length).trim();
        return playlistName ? `${t(language, "trackPanel.playlist")}: ${playlistName}` : t(language, "trackPanel.playlist");
    }
    if (panel.title === "Playlist") return t(language, "trackPanel.playlist");
    return panel.title;
};

const trackPanelEmptyText = (panel: NonNullable<TrackPanelState>, language: UiLanguage): string => (
    panel.panel === "queue" ? t(language, "trackPanel.queueEmpty") : t(language, "trackPanel.playlistEmpty")
);

const TRACK_PANEL_MIN_VISIBLE_ROWS = 4;

const TrackPanel = ({ panel, expanded = false, selectedIndex = 0, language = "en" }: {
    panel: TrackPanelState;
    expanded?: boolean;
    selectedIndex?: number;
    language?: UiLanguage;
}) => {
    if (!panel) return null;

    const panelRef = React.useRef<any>(null);
    const [panelHeight, setPanelHeight] = React.useState<number>(0);

    React.useEffect(() => {
        if (!panelRef.current) return;
        const { height } = measureElement(panelRef.current);
        if (height > 0 && height !== panelHeight) {
            setPanelHeight(height);
        }
    });

    const panelTitle = localizeTrackPanelTitle(panel, language);
    const isSpotifyThemePanel = panel.panel === "playlist" || panel.panel === "queue";

    const titleRows = 1;
    const hintRows = panel.hint ? 1 : 0;
    const paddingRows = 1;
    const availableRows = Math.max(
        TRACK_PANEL_MIN_VISIBLE_ROWS,
        panelHeight > 0 ? panelHeight - titleRows - hintRows - paddingRows - 2 : TRACK_PANEL_MIN_VISIBLE_ROWS,
    );

    const { items: rows, boundedIndex, startIndex } = visibleCommandWindow(
        panel.tracks,
        selectedIndex,
        availableRows,
    );

    return (
        <Box
            ref={panelRef}
            flexDirection="column"
            flexGrow={expanded ? 1 : 0}
            flexShrink={0}
            minHeight={0}
            height={expanded ? "100%" : undefined}
            paddingX={2}
            borderStyle="single"
            borderColor={isSpotifyThemePanel ? SPOTIFY_GREEN : BORDER_BLUE}
        >
            <Box>
                <Text bold color={isSpotifyThemePanel ? SPOTIFY_GREEN : "#f3b2c6"}>
                    {panelTitle}
                </Text>
                {panel.hint ? <Text color="#7f5d6b"> - {panel.hint}; Esc to hide</Text> : null}
            </Box>

            <Box flexDirection="column" paddingTop={2} flexGrow={0} flexShrink={0} minHeight={0}>
                {rows.length === 0 ? (
                    <Text color={isSpotifyThemePanel ? SPOTIFY_GREEN : "#7f5d6b"}>
                        {trackPanelEmptyText(panel, language)}
                    </Text>
                ) : rows.map((track, idx) => {
                    const absoluteIndex = startIndex + idx;
                    const selected = absoluteIndex === boundedIndex;
                    const selectedBackground = isSpotifyThemePanel && selected ? SPOTIFY_GREEN : undefined;
                    const rowColor = selectedBackground
                        ? SPOTIFY_SELECTED_TEXT
                        : isSpotifyThemePanel
                            ? "#ffffff"
                            : selected
                                ? "#f3b2c6"
                                : "#fff4f6";
                    const marker = selected ? "> " : "  ";
                    const spotifyLine = formatTrackPanelLine(track, TRACK_PANEL_ROW_WIDTH);
                    const rowBackgroundColor = selected ? (isSpotifyThemePanel ? SPOTIFY_GREEN : "#4b2f3a") : undefined;
                    const rowFill = rowBackgroundColor ? " ".repeat(Math.max(0, TRACK_PANEL_ROW_WIDTH - stringWidth(
                            isSpotifyThemePanel ? `${spotifyLine}` : `${marker}${track.index}${spotifyLine}`
                    ))) : "";

                    return (
                        <Text backgroundColor={rowBackgroundColor} wrap="truncate-end">
                            {isSpotifyThemePanel ? (
                                <Text color={rowColor} backgroundColor={rowBackgroundColor}>
                                    {spotifyLine}{rowFill}
                                </Text>
                            ) : (
                                <>
                                    <Text color={rowColor} backgroundColor={rowBackgroundColor}>{marker}</Text>
                                    <Text color="#bf98a7" backgroundColor={rowBackgroundColor}>{track.index}</Text>
                                    <Text color={rowColor} backgroundColor={rowBackgroundColor}>{spotifyLine}{rowFill}</Text>
                                </>
                            )}
                        </Text>
                    );
                })}
            </Box>
        </Box>
    );
};

const TrackPanelOverlay = ({ trackPanel, selectedIndex = 0, language = "en" }: {
    trackPanel: TrackPanelState;
    selectedIndex?: number;
    language?: UiLanguage;
}) => (
    <Box width="100%" height="100%" flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
        <TrackPanel panel={trackPanel} expanded={true} selectedIndex={selectedIndex} language={language} />
    </Box>
);

const CoverAtmosphere = ({ visual, art, compact }: {
    visual: CoverVisualModel;
    art: string | null;
    compact: boolean;
}) => {
    if (!compact && art) {
        return <Text>{art}</Text>;
    }

    const rows = compact ? visual.blocks.slice(0, 5) : visual.blocks;
    const columns = compact ? 7 : 14;

    return (
        <Box flexDirection="column">
            {rows.map((row, rowIndex) => (
                <Text key={rowIndex}>
                    {row.slice(0, columns).map((color, columnIndex) => (
                        <Text key={`${rowIndex}-${columnIndex}`} backgroundColor={color}>  </Text>
                    ))}
                </Text>
            ))}
        </Box>
    );
};

const CoverPatternArt = React.memo(({ pattern, variant }: {
    pattern: CoverPatternPayload;
    variant: CoverPatternVariant;
}) => {
    const rows = React.useMemo(() => renderCoverPatternHalfBlocks(variant.grid, pattern.palette), [variant, pattern.palette]);

    return (
        <Box flexDirection="column">
            {rows.map((row, rowIndex) => (
                <Text key={rowIndex}>
                    {row.map((cell, columnIndex) => (
                        <Text key={`${rowIndex}-${columnIndex}`} color={cell.foreground} backgroundColor={cell.background}>
                            {cell.char}
                        </Text>
                    ))}
                </Text>
            ))}
        </Box>
    );
});

const MINI_COVER_PATTERN_MAX_SIZE = 80;

const StaticCover = React.memo(({ visual, coverUrl, coverPattern, terminalSpace, compact, maxPatternSize }: {
    visual: CoverVisualModel;
    coverUrl: string | null;
    coverPattern: CoverPatternPayload | null;
    terminalSpace?: TerminalSpace;
    compact: boolean;
    maxPatternSize?: number;
}) => {
    const maxSize = maxPatternSize ?? (compact ? MINI_COVER_PATTERN_MAX_SIZE : 32);
    const patternDisplay = coverPattern
        ? resolveCoverPatternDisplay(coverPattern, terminalSpace, maxSize ? { maxSize } : undefined)
        : resolveCoverPatternDisplay(null, terminalSpace);
    const compactCoverWidth = Math.max(22, Math.min(48, (terminalSpace?.columns ?? 40) - 6));
    const compactCoverHeight = Math.max(8, Math.min(24, (terminalSpace?.rows ?? 22) - 8));
    const fetchableCoverUrl = patternDisplay.status === 'none' && isHttpCoverSource(coverUrl) ? coverUrl : null;
    const { art, failed } = useCoverArt(fetchableCoverUrl, compact ? compactCoverWidth : 32, compact ? compactCoverHeight : 16);
    const resolvedVisual = React.useMemo(() => coverVisualFromSource(coverUrl, failed), [coverUrl, failed]);
    const patternRequestedAt = React.useRef<number | null>(null);

    React.useEffect(() => {
        if (process.env.SONEX_PLAYER_DEBUG !== '1') return;
        if (!coverUrl) {
            patternRequestedAt.current = null;
            return;
        }
        if (!coverPattern) {
            if (patternRequestedAt.current === null) {
                patternRequestedAt.current = Date.now();
            }
            return;
        }
        if (patternRequestedAt.current !== null) {
            console.error(`[sonex-player-debug] cover pattern arrived in ${Date.now() - patternRequestedAt.current}ms url=${coverUrl}`);
            patternRequestedAt.current = null;
        }
    }, [coverUrl, coverPattern]);

    if (patternDisplay.status === 'unavailable') {
        return compact
            ? <Box flexGrow={1} flexShrink={1} minHeight={compactCoverHeight} />
            : <Box width={36} paddingRight={2} />;
    }

    if (patternDisplay.status === 'renderable' && coverPattern) {
        return (
            <Box flexGrow={compact ? 1 : 0} flexShrink={1} minHeight={compact ? compactCoverHeight : undefined} alignItems="center" justifyContent={compact ? 'flex-end' : 'center'}>
                <CoverPatternArt pattern={coverPattern} variant={patternDisplay.variant} />
            </Box>
        );
    }

    if (patternDisplay.status === 'unfit') {
        return compact
            ? <Box flexGrow={1} flexShrink={1} minHeight={compactCoverHeight} />
            : <Box width={36} paddingRight={2} />;
    }

    if (compact) {
        return (
            <Box flexGrow={1} flexShrink={1} minHeight={compactCoverHeight} alignItems="center" justifyContent="center">
                <CoverAtmosphere visual={resolvedVisual} art={art} compact={compact} />
            </Box>
        );
    }

    return (
        <Box width={36} paddingRight={2} flexDirection="column">
            <CoverAtmosphere visual={resolvedVisual} art={art} compact={compact} />
            <Text color={visual.muted}>{resolvedVisual.status === "fallback" ? "cover atmosphere" : "cover palette"}</Text>
        </Box>
    );
});

const PlayerMascot = ({ visual, frame, compact }: {
    visual: CoverVisualModel;
    frame: number;
    compact: boolean;
}) => {
    const pulse = ["▁", "▃", "▅", "▃"];
    const left = pulse[frame] ?? "▁";
    const right = pulse[(frame + 2) % pulse.length] ?? "▁";

    if (compact) {
        return (
            <Text>
                <Text color={visual.secondary}>{left}</Text>
                <Text color={visual.accent}> sonex </Text>
                <Text color={visual.secondary}>{right}</Text>
            </Text>
        );
    }

    const lift = frame === 1 || frame === 2 ? "  " : " ";
    return (
        <Box flexDirection="column" marginTop={1}>
            <Text>
                <Text color={visual.secondary}>{left}{left}</Text>
                <Text color={visual.accent}>  sonex signal  </Text>
                <Text color={visual.secondary}>{right}{right}</Text>
            </Text>
            <Text>
                <Text color={visual.muted}>{lift}</Text>
                <Text color={visual.primary}>╭─╮</Text>
                <Text color={visual.accent}>●</Text>
                <Text color={visual.primary}>╭─╮</Text>
            </Text>
            <Text>
                <Text color={visual.muted}>{frame === 3 ? " " : "  "}</Text>
                <Text color={visual.primary}>╰╥╯</Text>
                <Text color={visual.secondary}>▔</Text>
                <Text color={visual.primary}>╰╥╯</Text>
            </Text>
        </Box>
    );
};

const TrackDetails = React.memo(({ player, compact }: { player: PlayerState; compact: boolean }) => (
    <Box flexDirection="column">
        <Text bold color="#fff4f6">{player.name}</Text>
        <Text color="#bf98a7">{player.artist}</Text>
        {!compact || player.album !== "-" ? <Text color="#bf98a7">{player.album}</Text> : null}
    </Box>
));

const MiniPlayerStaticBody = React.memo(({
    player,
    visual,
    coverUrl,
    coverPattern,
    layout,
}: {
    player: PlayerState;
    visual: CoverVisualModel;
    coverUrl: string | null;
    coverPattern: CoverPatternPayload | null;
    layout: MiniPlayerLayout;
}) => {
    const infoInnerWidth = Math.max(0, layout.infoWidth - layout.infoLeftPadding);
    const statusLine = buildPlaybackStatusIconLine(player, infoInnerWidth);

    return (
        <Box flexDirection="row" width={layout.contentColumns} height={layout.contentRows}>
            <Box flexDirection="column" width={layout.infoWidth} flexShrink={0} paddingTop={layout.infoTop} paddingLeft={layout.infoLeftPadding}>
                <Box width={infoInnerWidth} justifyContent="center">
                    <Text bold color={BORDER_BLUE_SOFT} wrap="truncate-end">{player.name}</Text>
                </Box>
                <Box width={infoInnerWidth} justifyContent="center">
                    <Text color="#ffffff" wrap="truncate-end">{formatMiniTrackSubtitle(player.artist, player.album)}</Text>
                </Box>
                <Text>{' '.repeat(infoInnerWidth)}</Text>
                <Box width={infoInnerWidth}>
                    <Text>
                        {statusLine.segments.map((segment, index) => (
                            <Text key={index} color={segment.color}>{segment.text}</Text>
                        ))}
                    </Text>
                </Box>
            </Box>
            {layout.mode === 'artwork' ? (
                <Box
                    marginLeft={layout.gap}
                    width={layout.coverWidth}
                    height={layout.contentRows}
                    alignItems="center"
                    justifyContent="flex-end"
                    flexShrink={0}
                >
                    <StaticCover
                        visual={visual}
                        coverUrl={coverUrl}
                        coverPattern={coverPattern}
                        terminalSpace={{ columns: layout.coverWidth, rows: layout.contentRows }}
                        compact={true}
                    />
                </Box>
            ) : null}
        </Box>
    );
}, (prev, next) => (
    prev.player === next.player
    && prev.visual === next.visual
    && prev.coverUrl === next.coverUrl
    && prev.coverPattern === next.coverPattern
    && prev.layout === next.layout
));

const PlaybackMeter = ({ player, visual, compact = false, active = true }: {
    player: PlayerState;
    visual: CoverVisualModel;
    compact?: boolean;
    active?: boolean;
}) => {
    const progressMs = player.progress_ms ?? 0;
    const progress = formatDuration(progressMs);
    const duration = formatDuration(player.duration_ms);
    const progressBar = buildProgressBar(progressMs, player.duration_ms, 18);
    const isPlaying = active && player.is_playing === true;
    return (
        <Box flexDirection="column" marginTop={1}>
            <Text>
                <Text color="#bf98a7">{progress}</Text> <Text color={visual.secondary}>{progressBar}</Text> <Text color="#bf98a7">{duration}</Text>
            </Text>
            <Text color={isPlaying ? visual.accent : "#7f5d6b"}>{isPlaying ? "playing" : "paused"}</Text>
        </Box>
    );
};

const PlayerPane = ({ player, coverUrl, coverPattern, terminalSpace, miniLayout, variant = "full", active = true }: {
    player: PlayerState,
    coverUrl: string | null,
    coverPattern?: CoverPatternPayload | null,
    terminalSpace?: TerminalSpace,
    miniLayout?: MiniPlayerLayout,
    variant?: PlayerPaneVariant,
    active?: boolean
}) => {
    const compact = variant === "compact";
    const visual = React.useMemo(() => coverVisualFromSource(coverUrl, false), [coverUrl]);

    if (compact) {
        const layout = miniLayout ?? resolveMiniPlayerLayout(terminalSpace ?? { columns: null, rows: null });
        return (
            <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
                <MiniPlayerStaticBody
                    player={player}
                    visual={visual}
                    coverUrl={coverUrl}
                    coverPattern={coverPattern ?? null}
                    layout={layout}
                />
            </Box>
        );
    }

    return (
        <Box flexDirection="column" flexGrow={compact ? 1 : 1} flexShrink={1} minHeight={compact ? 8 : 20} padding={1} paddingX={compact ? 1 : 2}>
            {!compact ? (
                <Box marginBottom={1}>
                    <Text bold color={visual.accent}>Now Playing Stage</Text>
                </Box>
            ) : null}
            <Box marginTop={compact ? 0 : 1}>
                {!compact ? <StaticCover visual={visual} coverUrl={coverUrl} coverPattern={coverPattern ?? null} terminalSpace={terminalSpace} compact={compact} /> : null}
                <Box flexDirection="column" flexGrow={compact ? 0 : 1} flexShrink={0} paddingTop={compact ? 1 : 1}>
                    <TrackDetails player={player} compact={compact} />
                    <PlaybackMeter player={player} visual={visual} compact={compact} active={active} />
                    {!compact ? <PlayerMascot visual={visual} frame={0} compact={compact} /> : null}
                </Box>
            </Box>
        </Box>
    );
};

const LANGUAGE_CHOICES: UiLanguage[] = ["en", "zh-CN"];

const orderedLanguageChoices = (current: UiLanguage): UiLanguage[] => [
    current,
    ...LANGUAGE_CHOICES.filter((choice) => choice !== current),
];

const confirmCancelHint = (choices: ConfirmChoice[]): string => (
    choices.some((choice) => choice.label.includes("取消"))
        ? "按Esc退出"
        : "press Esc to cancel"
);

const PlaylistBrowsePanel = ({ choices, selectedIndex, spotifyTheme = false }: {
    choices: ConfirmChoice[];
    selectedIndex: number;
    spotifyTheme?: boolean;
}) => {
    if (choices.length === 0) return null;
    const { items: visibleChoices, boundedIndex, startIndex } = visibleCommandWindow(
        choices,
        selectedIndex,
        choices.length,
    );

    return (
        <Box flexDirection="column" marginTop={1}>
            {visibleChoices.map((choice, index) => {
                const absoluteIndex = startIndex + index;
                const selected = absoluteIndex === boundedIndex;
                const rowBackgroundColor = spotifyTheme && selected ? SPOTIFY_GREEN : undefined;
                const rowColor = rowBackgroundColor ? SPOTIFY_SELECTED_TEXT : selected ? BORDER_BLUE : "#fff4f6";
                const rowText = `${formatPlaylistBrowseName(choice.label)} ${playlistBrowseTrackCount(choice)}`;
                return (
                    <Text key={choice.value} backgroundColor={rowBackgroundColor} wrap="truncate-end">
                        <Text color={rowColor} backgroundColor={rowBackgroundColor}>{selected ? "> " : "  "}</Text>
                        <Text color={rowColor} backgroundColor={rowBackgroundColor}>{rowText}</Text>
                    </Text>
                );
            })}
        </Box>
    );
};

const CompactConfirm = ({ confirm, confirmIndex, spotifyTheme = false }: {
    confirm: ConfirmState;
    confirmIndex: number;
    spotifyTheme?: boolean;
}) => {
    if (!confirm) return null;
    const visibleChoices = getVisibleConfirmChoices(confirm.choices);
    const isSpotifyConfirm = spotifyTheme || confirm.tool_name === "spotify_device";

    if (confirm.tool_name === "playlist_browse") {
        return (
            <Box flexDirection="column" paddingX={1} paddingY={1} borderTop={true} borderStyle="single" borderColor={isSpotifyConfirm ? SPOTIFY_GREEN : BORDER_BLUE}>
                <Text color="#fff4f6">{confirm.message}</Text>
                <Text color="#7f5d6b">{confirmCancelHint(confirm.choices)}</Text>
                <PlaylistBrowsePanel choices={visibleChoices} selectedIndex={confirmIndex} spotifyTheme={isSpotifyConfirm} />
            </Box>
        );
    }

    return (
        <Box flexDirection="column" paddingX={1} paddingY={1} borderTop={true} borderStyle="single" borderColor={isSpotifyConfirm ? SPOTIFY_GREEN : BORDER_BLUE}>
            <Text color="#fff4f6">{confirm.message}</Text>
            <Text color="#7f5d6b">{confirmCancelHint(confirm.choices)}</Text>
            <ChoicePanel
                rows={visibleChoices.map((choice) => ({
                    key: choice.value,
                    label: choice.label,
                    description: choice.description,
                    display: choice.display,
                    labelWidth: CONFIRM_CHOICE_LABEL_WIDTH,
                }))}
                selectedIndex={confirmIndex}
                selectedBackgroundColor={isSpotifyConfirm ? SPOTIFY_GREEN : undefined}
            />
        </Box>
    );
};

const LanguagePanel = ({ panel, selectedIndex, language = "en" }: {
    panel: LanguagePanelState;
    selectedIndex: number;
    language?: UiLanguage;
}) => {
    if (!panel) return null;
    const choices = orderedLanguageChoices(panel.selected);
    const boundedIndex = Math.min(Math.max(selectedIndex, 0), choices.length - 1);
    return (
        <Box flexDirection="column" marginBottom={1} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE_SOFT}>
            <Text color="#fff4f6">{t(language, "language.title")}</Text>
            <Text color="#bf98a7">{t(language, "language.hint")}</Text>
            <ChoicePanel
                rows={choices.map((choice) => ({
                    key: choice,
                    label: choice === panel.selected ? `* ${languageLabel(choice)}` : languageLabel(choice),
                }))}
                selectedIndex={boundedIndex}
            />
            {panel.saveError ? <Text color="#ff9c9c">{panel.saveError}</Text> : null}
        </Box>
    );
};

type CompactSetupPanel = NonNullable<SpotifySetupState | AuthSetupState>;

const setupDoneHint = (setupPanel: CompactSetupPanel, language: UiLanguage): string | null => {
    if (setupPanel.active) return null;
    return language === "zh-CN" ? "按Esc键隐藏" : "press Esc to hide";
};

const setupMessageColor = (setupPanel: CompactSetupPanel): string => {
    const text = `${setupPanel.title} ${setupPanel.message}`.toLowerCase();
    if (text.includes("failed") || text.includes("失败")) return "#ff6b6b";
    if (text.includes("connected") || text.includes("success") || text.includes("成功")) return BORDER_BLUE_SOFT;
    return "#bf98a7";
};

const CompactSetup = ({
    setupPanel,
    input,
    setInput,
    onSubmit,
    inputPlaceholder,
    inputMask,
    inputFocus,
    inputRevision,
    language = "en",
    spotifyTheme = false,
}: {
    setupPanel: CompactSetupPanel | null;
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    inputPlaceholder: string;
    inputMask?: string;
    inputFocus: boolean;
    inputRevision: number;
    language?: UiLanguage;
    spotifyTheme?: boolean;
}) => {
    if (!setupPanel) return null;

    return (
        <Box flexDirection="column" paddingX={1} paddingY={1} borderTop={true} borderStyle="single" borderColor={spotifyTheme ? SPOTIFY_GREEN : BORDER_BLUE} flexShrink={0}>
            <Text color={spotifyTheme ? SPOTIFY_GREEN : "#fff4f6"}>{setupPanel.title}</Text>
            <Text color={setupMessageColor(setupPanel)}>{setupPanel.message}</Text>
            {setupDoneHint(setupPanel, language) ? <Text color="#7f5d6b">{setupDoneHint(setupPanel, language)}</Text> : null}
            {"provider" in setupPanel && setupPanel.providers && setupPanel.providers.length > 0 ? (
                <Text color="#9d7787">
                    {t(language, "providers.label")}: {setupPanel.providers.map((provider) => provider.value).join(" / ")}
                </Text>
            ) : null}
            {"provider" in setupPanel && setupPanel.methods && setupPanel.methods.length > 0 ? (
                <Text color="#9d7787">
                    {t(language, "methods.label")}: {setupPanel.methods.map((method) => method.value).join(" / ")}
                </Text>
            ) : null}
            {setupPanel.active && setupPanel.prompt ? (
                <Box flexDirection="row" marginTop={1}>
                    <Text color={spotifyTheme ? SPOTIFY_GREEN : "#7f5d6b"}>{"> "}</Text>
                    <PromptInput
                        input={input}
                        setInput={setInput}
                        onSubmit={onSubmit}
                        focus={inputFocus}
                        placeholder={setupPanel.prompt ?? inputPlaceholder}
                        mask={setupPanel.mask ? "*" : inputMask}
                        inputRevision={inputRevision}
                    />
                </Box>
            ) : null}
        </Box>
    );
};

const InputDock = ({
    input,
    setInput,
    onSubmit,
    inputPlaceholder,
    inputMask,
    inputFocus,
    inputRevision,
    confirm,
    confirmIndex,
    spotifyMode,
    spotifySetup,
    authSetup,
    slashSuggestions,
    slashIndex,
    helpPanel,
    helpPanelIndex,
    languagePanel,
    languagePanelIndex,
    modelPanelIndex,
    minimal = false,
    switchHint = null,
    language = "en",
}: {
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    inputPlaceholder: string;
    inputMask?: string;
    inputFocus: boolean;
    inputRevision: number;
    confirm: ConfirmState;
    confirmIndex: number;
    spotifyMode: SpotifyModeState;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
    slashSuggestions: SlashCommandSuggestion[];
    slashIndex: number;
    helpPanel: HelpPanelState;
    helpPanelIndex: number;
    languagePanel: LanguagePanelState;
    languagePanelIndex: number;
    modelPanelIndex: number;
    minimal?: boolean;
    switchHint?: string | null;
    language?: UiLanguage;
}) => {
    const selectedChoice = confirm?.choices[Math.min(confirmIndex, Math.max(0, confirm.choices.length - 1))] ?? null;
    const setupPanel = spotifySetup ?? (authSetup && authSetup.step !== "model" ? authSetup : null);
    const spotifyTheme = Boolean(spotifyMode?.enabled || spotifySetup);
    const modelPanel = authSetup?.active && authSetup.step === "model"
        ? {
            title: authSetup.title,
            hint: authSetup.message,
            rows: (authSetup.models ?? []).map((model) => ({
                key: model.value,
                label: formatModelPanelLabel(model),
                description: model.provider ?? model.value,
            })),
        }
        : null;
    const showInput = !setupPanel && !helpPanel && !languagePanel && !modelPanel && (!confirm || Boolean(selectedChoice?.input));
    const spotifyModeBorderLabel = " Spotify Mode ";

    return (
        <Box flexDirection="column">
            {!minimal ? (
                <Box flexDirection="column" flexShrink={0} paddingX={1}>
                    <HelpPanel panel={helpPanel} selectedIndex={helpPanelIndex} language={language} />
                    <SlashCommandList suggestions={slashSuggestions} selectedIndex={slashIndex} spotifyTheme={spotifyTheme} />
                    <CompactConfirm confirm={confirm} confirmIndex={confirmIndex} spotifyTheme={spotifyTheme} />
                    <LanguagePanel panel={languagePanel} selectedIndex={languagePanelIndex} language={language} />
                    {modelPanel ? (
                        <Box flexDirection="column" marginBottom={1} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE_SOFT}>
                            <Text color="#fff4f6">{modelPanel.title}</Text>
                            <Text color="#bf98a7">{modelPanel.hint}</Text>
                            <ChoicePanel rows={modelPanel.rows} selectedIndex={modelPanelIndex} visibleLimit={MAX_VISIBLE_MODEL_CHOICES} />
                        </Box>
                    ) : null}
                </Box>
            ) : null}
            {minimal ? <CompactConfirm confirm={confirm} confirmIndex={confirmIndex} spotifyTheme={spotifyTheme} /> : null}
            {setupPanel ? <CompactSetup
                setupPanel={setupPanel}
                input={input}
                setInput={setInput}
                onSubmit={onSubmit}
                inputPlaceholder={inputPlaceholder}
                inputMask={inputMask}
                inputFocus={inputFocus}
                inputRevision={inputRevision}
                language={language}
                spotifyTheme={Boolean(spotifySetup)}
            /> : null}
            {showInput ? (
                <>
                    <Box borderTop={true} borderBottom={true} borderLeft={false} borderRight={false}
                        borderStyle="single" borderColor={spotifyMode?.enabled ? SPOTIFY_GREEN : "#808791"}
                        paddingX={1} paddingTop={0} flexDirection="column"
                        minHeight={3} flexShrink={0}>
                        <Box flexDirection="row">
                            <Text color={spotifyMode?.enabled ? SPOTIFY_GREEN : "#7f5d6b"}>
                                {minimal && switchHint ? `${switchHint} · ` : ""}
                            </Text>
                            <PromptInput
                                input={input}
                                setInput={setInput}
                                onSubmit={onSubmit}
                                focus={inputFocus}
                                placeholder={inputPlaceholder}
                                mask={inputMask}
                                inputRevision={inputRevision}
                            />
                        </Box>
                    </Box>
                    <Box height={1} justifyContent="flex-end" paddingX={1}>
                        {spotifyMode?.enabled ? (
                            <Text bold color={SPOTIFY_GREEN}>{spotifyModeBorderLabel}</Text>
                        ) : null}
                    </Box>
                </>
            ) : null}
        </Box>
    );
};

const ConversationColumn = ({
    chatItems,
    input,
    setInput,
    onSubmit,
    inputPlaceholder,
    inputMask,
    inputFocus,
    inputRevision,
    confirm,
    confirmIndex,
    spotifyMode,
    spotifySetup,
    authSetup,
    slashSuggestions,
    slashIndex,
    helpPanel,
    helpPanelIndex,
    languagePanel,
    languagePanelIndex,
    modelPanelIndex,
    trackPanel,
    chatScrollOffset,
    onMaxChatScrollOffsetChange,
    language = "en",
    fill = false,
}: {
    chatItems: ChatItem[];
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    inputPlaceholder: string;
    inputMask?: string;
    inputFocus: boolean;
    inputRevision: number;
    confirm: ConfirmState;
    confirmIndex: number;
    spotifyMode: SpotifyModeState;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
    slashSuggestions: SlashCommandSuggestion[];
    slashIndex: number;
    helpPanel: HelpPanelState;
    helpPanelIndex: number;
    languagePanel: LanguagePanelState;
    languagePanelIndex: number;
    modelPanelIndex: number;
    trackPanel: TrackPanelState;
    chatScrollOffset: number;
    onMaxChatScrollOffsetChange: (value: number) => void;
    language?: UiLanguage;
    fill?: boolean;
}) => {
    const selectedChoice = confirm?.choices[Math.min(confirmIndex, Math.max(0, confirm.choices.length - 1))] ?? null;
    const hasModelPanel = authSetup?.active && authSetup.step === "model";
    const hasSetupPanel = Boolean(spotifySetup) || Boolean(authSetup && authSetup.step !== "model");
    const hasSlashPanel = slashSuggestions.length > 0;
    const showInput = !helpPanel && !languagePanel && !hasModelPanel && (!confirm || Boolean(selectedChoice?.input));
    const showMiniMascotStatus = showInput && !confirm && !hasSlashPanel && !hasSetupPanel;

    return (
        <Box flexDirection="column" flexGrow={fill ? 1 : 0} flexShrink={1} minHeight={0} height={fill ? "100%" : undefined}>
            <ChatPane items={chatItems} scrollOffset={chatScrollOffset} onMaxScrollOffsetChange={onMaxChatScrollOffsetChange} fill={fill} language={language} />
            {showMiniMascotStatus ? <MiniMascotStatus /> : null}
            <InputDock
                input={input}
                setInput={setInput}
                onSubmit={onSubmit}
                inputPlaceholder={inputPlaceholder}
                inputMask={inputMask}
                inputFocus={inputFocus}
                inputRevision={inputRevision}
                confirm={confirm}
                confirmIndex={confirmIndex}
                spotifyMode={spotifyMode}
                spotifySetup={spotifySetup}
                authSetup={authSetup}
                slashSuggestions={slashSuggestions}
                slashIndex={slashIndex}
                helpPanel={helpPanel}
                helpPanelIndex={helpPanelIndex}
                languagePanel={languagePanel}
                languagePanelIndex={languagePanelIndex}
                modelPanelIndex={modelPanelIndex}
                language={language}
            />
        </Box>
    );
};

/**
 * Coordinates the use visible snapshot on revision operation for the CLI UI runtime.
 *
 * @param value Input value used by the use visible snapshot on revision operation.
 * @param active Input value used by the use visible snapshot on revision operation.
 * @param snapshotRevision Input value used by the use visible snapshot on revision operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function useVisibleSnapshotOnRevision<T>(value: T, active: boolean, snapshotRevision: number): T {
    const snapshotRef = React.useRef(value);
    const revisionRef = React.useRef<number | null>(null);
    if (active && revisionRef.current !== snapshotRevision) {
        snapshotRef.current = value;
        revisionRef.current = snapshotRevision;
        return value;
    }
    if (!active) {
        revisionRef.current = null;
    }
    return snapshotRef.current;
}

const MiniPlayerRegion = ({
    player,
    coverUrl,
    coverPattern,
    terminalSpace,
    miniLayout,
    snapshotRevision,
}: {
    player: PlayerState;
    coverUrl: string | null;
    coverPattern: CoverPatternPayload | null;
    terminalSpace: TerminalSpace;
    miniLayout: MiniPlayerLayout;
    snapshotRevision: number;
}) => {
    const miniSnapshot = useVisibleSnapshotOnRevision({
        player,
        coverUrl,
        coverPattern,
        terminalSpace,
        miniLayout,
    }, true, snapshotRevision);

    return (
        <Box width="100%" height="100%" padding={0} flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
            <PlayerPane
                player={miniSnapshot.player}
                coverUrl={miniSnapshot.coverUrl}
                coverPattern={miniSnapshot.coverPattern}
                terminalSpace={miniSnapshot.terminalSpace}
                miniLayout={miniSnapshot.miniLayout}
                variant="compact"
                active={true}
            />
        </Box>
    );
};

const SpotifyImmersiveRegion = ({
    player,
    spotifyMode,
    terminalSpace,
    spotifyImmersiveLayout,
}: {
    player: PlayerState;
    spotifyMode: SpotifyModeState;
    terminalSpace: TerminalSpace;
    spotifyImmersiveLayout: SpotifyImmersiveLayout;
}) => {
    const deviceName = spotifyMode.device_name ?? "Spotify Connect";
    const deviceStatus = player.is_playing ? "playing" : "paused";
    const topPadding = spotifyImmersiveLayout.topPadding;
    const deviceWidth = spotifyImmersiveLayout.deviceSlot.width;

    return (
        <Box width="100%" height="100%" flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} paddingX={2} paddingTop={topPadding}>
            <Box justifyContent="center">
                <Text bold color={SPOTIFY_GREEN}>Spotify Mode</Text>
            </Box>
            <Box justifyContent="center" marginTop={1}>
                <Text color="#fff4f6" wrap="truncate-end">{player.name}</Text>
            </Box>
            <Box justifyContent="center">
                <Text color="#bf98a7" wrap="truncate-end">{formatMiniTrackSubtitle(player.artist, player.album)}</Text>
            </Box>
            <Box height={1} marginTop={1} />
            <Box justifyContent="center">
                <Box width={deviceWidth > 0 ? deviceWidth : undefined} justifyContent="center">
                    <Text color={SPOTIFY_GREEN} wrap="truncate-end">{deviceStatus} on {deviceName}</Text>
                </Box>
            </Box>
        </Box>
    );
};

const ConversationRegion = ({
    chatItems,
    input,
    setInput,
    onSubmit,
    inputPlaceholder,
    inputMask,
    inputFocus,
    inputRevision,
    confirm,
    confirmIndex,
    spotifyMode,
    spotifySetup,
    authSetup,
    slashSuggestions,
    slashIndex,
    helpPanel,
    helpPanelIndex,
    languagePanel,
    languagePanelIndex,
    modelPanelIndex,
    trackPanel,
    trackPanelIndex,
    chatScrollOffset,
    onMaxChatScrollOffsetChange,
    language = "en",
}: {
    chatItems: ChatItem[];
    statusText: string;
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    inputPlaceholder: string;
    inputMask?: string;
    inputFocus: boolean;
    inputRevision: number;
    confirm: ConfirmState;
    confirmIndex: number;
    spotifyMode: SpotifyModeState;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
    slashSuggestions: SlashCommandSuggestion[];
    slashIndex: number;
    helpPanel: HelpPanelState;
    helpPanelIndex: number;
    languagePanel: LanguagePanelState;
    languagePanelIndex: number;
    modelPanelIndex: number;
    trackPanel: TrackPanelState;
    trackPanelIndex: number;
    chatScrollOffset: number;
    onMaxChatScrollOffsetChange: (value: number) => void;
    language?: UiLanguage;
}) => {
    if (trackPanel) {
        return <TrackPanelOverlay trackPanel={trackPanel} selectedIndex={trackPanelIndex} language={language} />;
    }

    return (
        <Box width="100%" height="100%" flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
            <ConversationColumn
            chatItems={chatItems}
            input={input}
            setInput={setInput}
            onSubmit={onSubmit}
            inputPlaceholder={inputPlaceholder}
            inputMask={inputMask}
            inputFocus={inputFocus}
            inputRevision={inputRevision}
            confirm={confirm}
            confirmIndex={confirmIndex}
            spotifyMode={spotifyMode}
            spotifySetup={spotifySetup}
            authSetup={authSetup}
            slashSuggestions={slashSuggestions}
            slashIndex={slashIndex}
            helpPanel={helpPanel}
            helpPanelIndex={helpPanelIndex}
            languagePanel={languagePanel}
            languagePanelIndex={languagePanelIndex}
            modelPanelIndex={modelPanelIndex}
            trackPanel={trackPanel}
            chatScrollOffset={chatScrollOffset}
            onMaxChatScrollOffsetChange={onMaxChatScrollOffsetChange}
            language={language}
            fill={true}
            />
        </Box>
    );
};

export const DynamicShell = ({
    input,
    setInput,
    onSubmit,
    inputPlaceholder,
    inputMask,
    inputFocus,
    inputRevision,
    chatItems,
    player,
    statusText,
    coverUrl,
    coverPattern,
    confirm,
    confirmIndex,
    spotifyMode,
    spotifySetup,
    authSetup,
    slashSuggestions,
    slashIndex,
    helpPanel,
    helpPanelIndex,
    languagePanel,
    languagePanelIndex,
    modelPanelIndex,
    trackPanel,
    trackPanelIndex,
    activeRegion,
    miniSnapshotRevision,
    miniLayout,
    spotifyImmersiveLayout,
    chatScrollOffset,
    onMaxChatScrollOffsetChange,
    terminalSpace,
    language = "en",
}: {
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    inputPlaceholder: string;
    inputMask?: string;
    inputFocus: boolean;
    inputRevision: number;
    chatItems: ChatItem[];
    player: PlayerState;
    statusText: string;
    coverUrl: string | null;
    coverPattern: CoverPatternPayload | null;
    confirm: ConfirmState;
    confirmIndex: number;
    spotifyMode: SpotifyModeState;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
    slashSuggestions: SlashCommandSuggestion[];
    slashIndex: number;
    helpPanel: HelpPanelState;
    helpPanelIndex: number;
    languagePanel: LanguagePanelState;
    languagePanelIndex: number;
    modelPanelIndex: number;
    trackPanel: TrackPanelState;
    trackPanelIndex: number;
    activeRegion: ShellRegion;
    miniSnapshotRevision: number;
    miniLayout: MiniPlayerLayout;
    spotifyImmersiveLayout: SpotifyImmersiveLayout;
    chatScrollOffset: number;
    onMaxChatScrollOffsetChange: (value: number) => void;
    terminalSpace: TerminalSpace;
    language?: UiLanguage;
}) => {
    if (activeRegion === "miniPlayer") {
        return (
            <MiniPlayerRegion
                player={player}
                coverUrl={coverUrl}
                coverPattern={coverPattern}
                terminalSpace={terminalSpace}
                miniLayout={miniLayout}
                snapshotRevision={miniSnapshotRevision}
            />
        );
    }

    if (activeRegion === "spotifyImmersive") {
        return (
            <SpotifyImmersiveRegion
                player={player}
                spotifyMode={spotifyMode}
                terminalSpace={terminalSpace}
                spotifyImmersiveLayout={spotifyImmersiveLayout}
            />
        );
    }

    return (
        <ConversationRegion
            chatItems={chatItems}
            statusText={statusText}
            input={input}
            setInput={setInput}
            onSubmit={onSubmit}
            inputPlaceholder={inputPlaceholder}
            inputMask={inputMask}
            inputFocus={inputFocus}
            inputRevision={inputRevision}
            confirm={confirm}
            confirmIndex={confirmIndex}
            spotifyMode={spotifyMode}
            spotifySetup={spotifySetup}
            authSetup={authSetup}
            slashSuggestions={slashSuggestions}
            slashIndex={slashIndex}
            helpPanel={helpPanel}
            helpPanelIndex={helpPanelIndex}
            languagePanel={languagePanel}
            languagePanelIndex={languagePanelIndex}
            modelPanelIndex={modelPanelIndex}
            trackPanel={trackPanel}
            trackPanelIndex={trackPanelIndex}
            chatScrollOffset={chatScrollOffset}
            onMaxChatScrollOffsetChange={onMaxChatScrollOffsetChange}
            language={language}
        />
    );
};

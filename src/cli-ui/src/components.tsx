import React from 'react';
import { Box, Text, measureElement } from 'ink';
import TextInput from 'ink-text-input';
import stringWidth from 'string-width';
import { APP_VERSION, BORDER_BLUE, BORDER_BLUE_SOFT, FALLBACK_MODEL_NAME, MAX_VISIBLE_MODEL_CHOICES, MAX_VISIBLE_SLASH_COMMANDS, SONEX_MASCOT, SONEX_MASCOT_MICRO } from './constants.js';
import { HELP_PANEL_VISIBLE_COMMANDS, helpPanelCommands, visibleCommandWindow } from './command-panel.js';
import { getVisibleConfirmChoices } from './confirm-choice.js';
import { buildProgressBar, formatDuration, formatMiniTrackSubtitle } from './format.js';
import { getVisibleChatWindow } from './chat-window.js';
import { isHttpCoverSource, useCoverArt } from './hooks.js';
import { languageLabel, t } from './i18n.js';
import { coverVisualFromSource, type CoverVisualModel } from './cover-visual.js';
import { renderCoverPatternHalfBlocks, resolveCoverPatternDisplay, type CoverPatternPayload, type CoverPatternVariant, type TerminalSpace } from './cover-pattern.js';
import { resolveMiniPlayerLayout, type ChatHeaderVariant, type MiniPlayerLayout, type ShellRegion } from './layout.js';
import { buildPlaybackStatusIconLine } from './mini-progress-writer.js';
import type { ActivityItem, ActivityKind, AuthMethodChoice, AuthRuntimeState, AuthSetupState, ChatBubbleProps, ChatItem, ConfirmChoice, ConfirmState, HelpPanelState, LanguagePanelState, LoginScreenProps, PlayerPaneVariant, PlayerState, PromptInputProps, SlashCommandSuggestion, SpotifySetupState, TrackPanelState, TrackPanelTrack, TrackSummary, UiLanguage } from './types.js';

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
            <Box width="100%" height={4} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE} flexDirection="column">
                <Text><Text bold color="#fff4f6">Sonex CLI</Text> <Text color="#bf98a7">v{APP_VERSION}</Text></Text>
                <Text color="#d8bcc7" wrap="truncate-end">{identity}</Text>
            </Box>
        );
    }

    return (
        <Box width="100%" minHeight={9} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE}>
            <Mascot />
            <Box flexDirection="column" justifyContent="flex-start">
                <Text><Text bold color="#fff4f6">Sonex CLI</Text> <Text color="#bf98a7">v{APP_VERSION}</Text></Text>
                <Text color="#d8bcc7">{identity}</Text>
                <Text color="#bf98a7">~/dev/sonex</Text>
                <Text color={BORDER_BLUE_SOFT}>{t(language, "tips.placeholder")}</Text>
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

const PromptInput = ({ input, setInput, onSubmit, focus, placeholder, mask, inputRevision }: PromptInputProps) => (
    <TextInput
        key={inputRevision}
        value={input}
        onChange={setInput}
        onSubmit={onSubmit}
        focus={focus}
        placeholder={placeholder}
        mask={mask}
    />
);

type ChoicePanelRow = {
    key: string;
    label: string;
    description?: string | null;
    labelWidth?: number;
};

const COMMAND_LIST_LABEL_WIDTH = 12;
const CONFIRM_CHOICE_LABEL_WIDTH = 18;
const MODEL_PANEL_LABEL_WIDTH = 20;

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

const formatChoicePanelLabel = (row: ChoicePanelRow): string => (
    row.labelWidth
        ? row.label + " ".repeat(Math.max(0, row.labelWidth - stringWidth(row.label)))
        : row.label
);

const ChoicePanel = ({ rows, selectedIndex, visibleLimit }: {
    rows: ChoicePanelRow[];
    selectedIndex: number;
    visibleLimit?: number;
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
                const rowColor = absoluteIndex === boundedIndex ? BORDER_BLUE : "#fff4f6";
                return (
                    <Text key={row.key}>
                        <Text color={rowColor}>{absoluteIndex === boundedIndex ? "> " : "  "}</Text>
                        <Text color={rowColor}>{formatChoicePanelLabel(row)}</Text>
                        {row.description ? (
                            <>
                                <Text color={rowColor}>{row.description}</Text>
                            </>
                        ) : null}
                    </Text>
                );
            })}
        </Box>
    );
};

const SlashCommandList = ({ suggestions, selectedIndex }: {
    suggestions: SlashCommandSuggestion[];
    selectedIndex: number;
}) => {
    if (suggestions.length === 0) return null;

    const { items: visibleSuggestions, boundedIndex, startIndex } = visibleCommandWindow(
        suggestions,
        selectedIndex,
        MAX_VISIBLE_SLASH_COMMANDS,
    );

    return (
        <Box flexDirection="column" paddingX={1}>
            {visibleSuggestions.map((command, index) => {
                const absoluteIndex = startIndex + index;
                const commandColor = absoluteIndex === boundedIndex ? BORDER_BLUE : "#fff4f6";
                return (
                    <Text key={command.name}>
                        <Text color={commandColor}>
                            {absoluteIndex === boundedIndex ? "> " : "  "}
                        </Text>
                        <Text color={commandColor}>{formatCommandListLabel(command)}</Text>
                        <Text color={commandColor}>{command.description}</Text>
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

const ChatBubble = ({ role, content }: ChatBubbleProps) => {
    const isUser = role === "user";
    const color = isUser ? "#fff6f8" : "#f6e9ee";
    const borderLeftColor = isUser ? BORDER_BLUE : BORDER_BLUE_SOFT;

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
                            <ChatBubble key={`${items.indexOf(chat)}_${idx}`} role={chat.role} content={chat.content} />
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

const TrackPanel = ({ panel, expanded = false, language = "en" }: { panel: TrackPanelState; expanded?: boolean; language?: UiLanguage }) => {
    if (!panel) return null;
    const rows: TrackPanelTrack[] = panel.tracks.slice(0, 10);
    const panelTitle = localizeTrackPanelTitle(panel, language);
    return (
        <Box
            flexDirection="column"
            flexGrow={expanded ? 1 : 0}
            flexShrink={1}
            minHeight={expanded ? 0 : 9}
            height={expanded ? "100%" : undefined}
            padding={1}
            paddingX={2}
            borderStyle="single"
            borderColor={BORDER_BLUE}
        >
            <Box marginBottom={1}>
                <Text bold color="#f3b2c6">{panelTitle}</Text>
                {panel.hint ? <Text color="#7f5d6b"> - {panel.hint}; Esc to hide</Text> : null}
            </Box>
            <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} paddingTop={1}>
                {rows.length === 0 ? (
                    <Text color="#7f5d6b">{trackPanelEmptyText(panel, language)}</Text>
                ) : rows.map((track, idx) => {
                    const marker = idx === 0 ? <Text color="#f3b2c6">{">>"}</Text> :
                        <Text color="#7f5d6b">{".."}</Text>;
                    const meta = panel.panel === "queue" ? track.duration : `${track.artist} • ${track.duration}`;
                    return (
                        <Box key={`${track.index}_${idx}`} flexDirection="column" marginBottom={1}>
                            <Text>{marker} <Text color="#bf98a7">{track.index}</Text> <Text
                                color="#fff4f6">{track.title}</Text></Text>
                            <Text> <Text color="#bf98a7">{meta}</Text></Text>
                        </Box>
                    );
                })}
            </Box>
        </Box>
    );
};

const TrackPanelOverlay = ({ trackPanel, language = "en" }: { trackPanel: TrackPanelState; language?: UiLanguage }) => (
    <Box width="100%" height="100%" flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
        <TrackPanel panel={trackPanel} expanded={true} language={language} />
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

const CompactConversation = ({ items, statusText }: { items: ChatItem[]; statusText: string }) => {
    const visibleItems = items.slice(-2);

    return (
        <Box flexDirection="column" paddingX={1} paddingY={1} minHeight={4}>
            {visibleItems.length === 0 ? (
                <Text color={BORDER_BLUE}>{statusText}</Text>
            ) : (
                visibleItems.map((item, idx) => (
                    <Text key={idx} color={item.role === "user" ? "#fff4f6" : "#bf98a7"}>
                        <Text color="#7f5d6b">{item.role === "user" ? ">" : "<"}</Text> {item.content}
                    </Text>
                ))
            )}
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

const CompactConfirm = ({ confirm, confirmIndex }: { confirm: ConfirmState; confirmIndex: number }) => {
    if (!confirm) return null;
    const visibleChoices = getVisibleConfirmChoices(confirm.choices);

    return (
        <Box flexDirection="column" paddingX={1} paddingY={1} borderTop={true} borderStyle="single" borderColor={BORDER_BLUE}>
            <Text color="#fff4f6">{confirm.message}</Text>
            <Text color="#7f5d6b">{confirmCancelHint(confirm.choices)}</Text>
            <ChoicePanel
                rows={visibleChoices.map((choice) => ({
                    key: choice.value,
                    label: choice.label,
                    description: choice.description,
                    labelWidth: CONFIRM_CHOICE_LABEL_WIDTH,
                }))}
                selectedIndex={confirmIndex}
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

const CompactSetup = ({ spotifySetup, authSetup, language = "en" }: { spotifySetup: SpotifySetupState; authSetup: AuthSetupState; language?: UiLanguage }) => {
    if (authSetup && authSetup.provider === "apple_music") {
        return (
            <Box flexDirection="column" paddingX={1} paddingY={1} borderTop={true} borderStyle="single" borderColor={BORDER_BLUE}>
                <Text color="#fff4f6">{authSetup.title}</Text>
                <Text color="#bf98a7">{authSetup.message}</Text>
                {authSetup.providers && authSetup.providers.length > 0 ? (
                    <Text color="#9d7787">
                        {t(language, "providers.label")}: {authSetup.providers.map((provider) => provider.value).join(" / ")}
                    </Text>
                ) : null}
                {authSetup.methods && authSetup.methods.length > 0 ? (
                    <Text color="#9d7787">
                        {t(language, "methods.label")}: {authSetup.methods.map((method) => method.value).join(" / ")}
                    </Text>
                ) : null}
                {authSetup.active && authSetup.prompt ? (
                    <Text color="#9d7787">{t(language, "input.label")}: {authSetup.prompt}</Text>
                ) : null}
            </Box>
        );
    }

    if (!spotifySetup) return null;

    return (
        <Box flexDirection="column" paddingX={1} paddingY={1} borderTop={true} borderStyle="single" borderColor={BORDER_BLUE}>
            <Text color="#fff4f6">{spotifySetup.title}</Text>
            <Text color="#bf98a7">{spotifySetup.message}</Text>
            {spotifySetup.active && spotifySetup.prompt ? (
                <Text color="#9d7787">{t(language, "input.label")}: {spotifySetup.prompt}</Text>
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
    const showInput = !helpPanel && !languagePanel && !modelPanel && (!confirm || Boolean(selectedChoice?.input));

    return (
        <Box flexDirection="column">
            {!minimal ? (
                <Box flexDirection="column" flexShrink={0} paddingX={1}>
                    <HelpPanel panel={helpPanel} selectedIndex={helpPanelIndex} language={language} />
                    <SlashCommandList suggestions={slashSuggestions} selectedIndex={slashIndex} />
                    <CompactConfirm confirm={confirm} confirmIndex={confirmIndex} />
                    <LanguagePanel panel={languagePanel} selectedIndex={languagePanelIndex} language={language} />
                    {modelPanel ? (
                        <Box flexDirection="column" marginBottom={1} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE_SOFT}>
                            <Text color="#fff4f6">{modelPanel.title}</Text>
                            <Text color="#bf98a7">{modelPanel.hint}</Text>
                            <ChoicePanel rows={modelPanel.rows} selectedIndex={modelPanelIndex} visibleLimit={MAX_VISIBLE_MODEL_CHOICES} />
                        </Box>
                    ) : null}
                    {!modelPanel ? <CompactSetup spotifySetup={spotifySetup} authSetup={authSetup} language={language} /> : null}
                </Box>
            ) : null}
            {minimal ? <CompactConfirm confirm={confirm} confirmIndex={confirmIndex} /> : null}
            {showInput ? (
                <Box borderTop={true} borderStyle="single" borderColor={BORDER_BLUE} paddingX={1} paddingTop={0} paddingBottom={1} flexDirection="row"
                    minHeight={minimal ? 3 : 4} flexShrink={0}>
                    <Text color="#7f5d6b">{minimal && switchHint ? `${switchHint} · > ` : "> "}</Text>
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
    const hasSetupPanel = spotifySetup?.active || (authSetup?.active && authSetup.step !== "model");
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
}) => {
    if (trackPanel) {
        return <TrackPanelOverlay trackPanel={trackPanel} language={language} />;
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
    activeRegion,
    miniSnapshotRevision,
    miniLayout,
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
    activeRegion: ShellRegion;
    miniSnapshotRevision: number;
    miniLayout: MiniPlayerLayout;
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
        />
    );
};

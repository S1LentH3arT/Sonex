import React from 'react';
import { Box, Text, measureElement } from 'ink';
import TextInput from 'ink-text-input';
import { APP_TIP_PLACEHOLDER, APP_VERSION, BORDER_BLUE, BORDER_BLUE_SOFT, FALLBACK_MODEL_NAME, MAX_VISIBLE_MODEL_CHOICES, MAX_VISIBLE_SLASH_COMMANDS, SONEX_MASCOT } from './constants.js';
import { HELP_PANEL_VISIBLE_COMMANDS, helpPanelCommands, visibleCommandWindow } from './command-panel.js';
import { buildProgressBar, formatDuration, formatMiniTrackSubtitle } from './format.js';
import { getVisibleChatWindow } from './chat-window.js';
import { isHttpCoverSource, useCoverArt } from './hooks.js';
import { coverVisualFromSource, type CoverVisualModel } from './cover-visual.js';
import { renderCoverPatternHalfBlocks, resolveCoverPatternDisplay, type CoverPatternPayload, type CoverPatternVariant, type TerminalSpace } from './cover-pattern.js';
import { resolveMiniPlayerLayout, type ChatHeaderVariant, type MiniPlayerLayout, type ShellRegion } from './layout.js';
import type { ActivityItem, ActivityKind, AuthMethodChoice, AuthRuntimeState, AuthSetupState, ChatBubbleProps, ChatItem, ConfirmState, HelpPanelState, LoginScreenProps, PlayerPaneVariant, PlayerState, PromptInputProps, SlashCommandSuggestion, SpotifySetupState, TrackSummary } from './types.js';

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

export const HeaderFrame = ({ authState, variant }: { authState: AuthRuntimeState; variant: ChatHeaderVariant }) => {
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
                <Text color={BORDER_BLUE_SOFT}>{APP_TIP_PLACEHOLDER}</Text>
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
}: LoginScreenProps) => {
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
        ? "A little warm-up before we get started."
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
                        <Text color="#7f5d6b">Use Up/Down to choose, Enter to continue.</Text>
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
                        <Text color={BORDER_BLUE_SOFT}>Waiting for browser authorization...</Text>
                        <Text color="#7f5d6b">Complete the OAuth flow in your browser, then return here.</Text>
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
                        <Text color={commandColor}>{command.usage}</Text>
                        <Text color={commandColor}> - </Text>
                        <Text color={commandColor}>{command.description}</Text>
                    </Text>
                );
            })}
        </Box>
    );
};

const HelpPanel = ({ panel, selectedIndex }: { panel: HelpPanelState; selectedIndex: number }) => {
    if (!panel) return null;
    const commands = helpPanelCommands(panel.commands);
    const { items: visibleCommands, boundedIndex, startIndex } = visibleCommandWindow(
        commands,
        selectedIndex,
        HELP_PANEL_VISIBLE_COMMANDS,
    );

    return (
        <Box flexDirection="column" paddingX={1} paddingBottom={1}>
            <Text>
                <Text bold color="#fff4f6">{panel.title}</Text>
                <Text color="#7f5d6b"> - </Text>
                <Text color="#9d7787">{panel.hint}</Text>
            </Text>
            {panel.commands.length === 0 ? (
                <Text color="#7f5d6b">No matching commands.</Text>
            ) : visibleCommands.map((command, index) => {
                const absoluteIndex = startIndex + index;
                const commandColor = absoluteIndex === boundedIndex ? BORDER_BLUE : "#fff4f6";
                return (
                    <Text key={command.name}>
                        <Text color={commandColor}>
                            {absoluteIndex === boundedIndex ? "> " : "  "}
                        </Text>
                        <Text color={commandColor}>{command.usage}</Text>
                        <Text color={commandColor}> - </Text>
                        <Text color={commandColor}>{command.description}</Text>
                    </Text>
                );
            })}
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

const ChatPane = ({ items, scrollOffset, onMaxScrollOffsetChange, fill = false }: {
    items: ChatItem[];
    scrollOffset: number;
    onMaxScrollOffsetChange: (value: number) => void;
    fill?: boolean;
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
            <Box marginBottom={1} flexShrink={0}>
                <Text bold color={BORDER_BLUE}>Conversation</Text>
            </Box>
            <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} overflowY="hidden">
                {items.length === 0 ? (
                    <Text color="#7f5d6b">No messages yet.</Text>
                ) : (
                    <>
                        {visibleWindow.hasHiddenAbove ? <Text color="#7f5d6b">↑ earlier messages</Text> : null}
                        {visibleWindow.items.map((chat, idx) => (
                            <ChatBubble key={`${items.indexOf(chat)}_${idx}`} role={chat.role} content={chat.content} />
                        ))}
                        {visibleWindow.hasHiddenBelow ? <Text color="#7f5d6b">↓ newer messages</Text> : null}
                    </>
                )}
            </Box>
        </Box>
    );
};

const QueuePane = ({ tracks }: { tracks: Array<{ index: string; title: string; artist: string; duration: string }> }) => (
    <Box flexDirection="column" minHeight={9} padding={1} paddingX={2} borderBottom={true} borderStyle="single"
        borderColor={BORDER_BLUE}>
        <Box marginBottom={1}>
            <Text bold color="#f3b2c6">Queue / Playlist</Text>
        </Box>
        <Box flexDirection="column" paddingTop={1}>
            {tracks.length === 0 ? (
                <Text color="#7f5d6b">Queue is empty.</Text>
            ) : tracks.map((track, idx) => {
                const marker = track.index === "01" ? <Text color="#f3b2c6">{">>"}</Text> :
                    <Text color="#7f5d6b">{".."}</Text>;
                return (
                    <Box key={idx} flexDirection="column" marginBottom={1}>
                        <Text>{marker} <Text color="#bf98a7">{track.index}</Text> <Text
                            color="#fff4f6">{track.title}</Text></Text>
                        <Text> <Text color="#bf98a7">{track.artist}</Text> <Text color="#7f5d6b">•</Text> <Text
                            color="#bf98a7">{track.duration}</Text></Text>
                    </Box>
                );
            })}
        </Box>
    </Box>
);

const SearchResultsPane = ({ tracks }: { tracks: TrackSummary[] }) => (
    <Box flexDirection="column" minHeight={12} padding={1} paddingX={2} borderBottom={true} borderStyle="single"
        borderColor={BORDER_BLUE}>
        <Box marginBottom={1}>
            <Text bold color="#f3b2c6">Search Results</Text>
        </Box>
        <Box flexDirection="column">
            {tracks.length === 0 ? (
                <Text color="#7f5d6b">No Spotify results yet.</Text>
            ) : tracks.slice(0, 6).map((track, idx) => {
                const marker = idx === 0 ? <Text color="#f3b2c6">{">>"}</Text> :
                    <Text color="#7f5d6b">{".."}</Text>;
                return (
                    <Box key={`${track.uri ?? track.index}_${idx}`} flexDirection="column" marginBottom={1}>
                        <Text>{marker} <Text color="#bf98a7">{track.index}</Text> <Text
                            color="#fff4f6">{track.title || track.name}</Text></Text>
                        <Text> <Text color="#bf98a7">{track.artist}</Text> <Text color="#7f5d6b">•</Text> <Text
                            color="#bf98a7">{track.album}</Text> <Text color="#7f5d6b">•</Text> <Text
                                color="#bf98a7">{track.duration}</Text></Text>
                        {track.recommendation_reason ? (
                            <Text color="#9d7787"> {track.recommendation_reason}</Text>
                        ) : null}
                    </Box>
                );
            })}
        </Box>
    </Box>
);

const ActivityPane = ({ items, confirm, confirmIndex, spotifySetup, authSetup }: {
    items: ActivityItem[];
    confirm: ConfirmState;
    confirmIndex: number;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
}) => {
    const colors: Record<ActivityKind, string> = {
        tool: "#8fd3ff",
        status: "#bf98a7",
        error: "#ff9c9c",
        confirm: "#f3b2c6",
    };

    return (
        <Box flexDirection="column" flexGrow={1} minHeight={14} padding={1} paddingX={2} borderBottom={true}
            borderStyle="single" borderColor={BORDER_BLUE}>
            <Box marginBottom={1}>
                <Text bold color="#f3b2c6">Activity</Text>
            </Box>
            {confirm && (
                <Box flexDirection="column" marginBottom={1} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE_SOFT}>
                    <Text color="#fff4f6">{confirm.message}</Text>
                    <Text color="#bf98a7">{confirm.tool_name} {JSON.stringify(confirm.tool_args)}</Text>
                    <Box flexDirection="column">
                        {confirm.choices.map((choice, idx) => (
                            <Box key={choice.value} flexDirection="column">
                                <Text color={confirmIndex === idx ? "#fff4f6" : "#7f5d6b"}>
                                    {confirmIndex === idx ? "> " : "  "}{choice.label}
                                </Text>
                                {choice.description ? (
                                    <Text color="#8f6f7c">    {choice.description}</Text>
                                ) : null}
                            </Box>
                        ))}
                    </Box>
                </Box>
            )}
            {spotifySetup && (
                <Box flexDirection="column" marginBottom={1} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE_SOFT}>
                    <Text color="#fff4f6">{spotifySetup.title}</Text>
                    <Text color="#bf98a7">{spotifySetup.message}</Text>
                    {spotifySetup.active && spotifySetup.prompt ? (
                        <Text color="#9d7787">Input: {spotifySetup.prompt}</Text>
                    ) : null}
                </Box>
            )}
            {authSetup && (
                <Box flexDirection="column" marginBottom={1} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE_SOFT}>
                    <Text color="#fff4f6">{authSetup.title}</Text>
                    <Text color="#bf98a7">{authSetup.message}</Text>
                    {authSetup.methods && authSetup.methods.length > 0 ? (
                        <Text color="#9d7787">
                            {authSetup.methods.map((method) => method.value).join(" / ")}
                        </Text>
                    ) : null}
                    {authSetup.active && authSetup.prompt ? (
                        <Text color="#9d7787">Input: {authSetup.prompt}</Text>
                    ) : null}
                </Box>
            )}
            <Box flexDirection="column" flexGrow={1}>
                {items.length === 0 ? (
                    <Text color="#7f5d6b">Waiting for agent activity.</Text>
                ) : (
                    items.map((item) => {
                        const statusColor = item.status === "error" ? "#ff9c9c" :
                            item.status === "success" ? "#a4e7b1" : "#bf98a7";
                        return (
                            <Box key={item.id} flexDirection="column" marginBottom={1} borderStyle="single"
                                borderTop={false} borderRight={false} borderBottom={false} borderLeft={true}
                                borderColor={BORDER_BLUE_SOFT} paddingX={1}>
                                <Text>
                                    <Text color={colors[item.kind]}>{item.kind}</Text>
                                    <Text color="#7f5d6b"> • </Text>
                                    <Text color={statusColor}>{item.status ?? "pending"}</Text>
                                </Text>
                                <Text color="#fff4f6">{item.title}</Text>
                                {item.detail ? <Text color="#bf98a7">{item.detail}</Text> : null}
                            </Box>
                        );
                    })
                )}
            </Box>
        </Box>
    );
};

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

const StaticCover = React.memo(({ visual, coverUrl, coverPattern, terminalSpace, compact, maxPatternSize }: {
    visual: CoverVisualModel;
    coverUrl: string | null;
    coverPattern: CoverPatternPayload | null;
    terminalSpace?: TerminalSpace;
    compact: boolean;
    maxPatternSize?: number;
}) => {
    const maxSize = maxPatternSize ?? (compact ? undefined : 32);
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

const CompactConfirm = ({ confirm, confirmIndex }: { confirm: ConfirmState; confirmIndex: number }) => {
    if (!confirm) return null;

    return (
        <Box flexDirection="column" paddingX={1} paddingY={1} borderTop={true} borderStyle="single" borderColor={BORDER_BLUE}>
            <Text color="#fff4f6">{confirm.message}</Text>
            {confirm.choices.map((choice, idx) => (
                <Box key={choice.value} flexDirection="column">
                    <Text color={confirmIndex === idx ? "#fff4f6" : "#7f5d6b"}>
                        {confirmIndex === idx ? "> " : "  "}{choice.label}
                    </Text>
                    {choice.description ? (
                        <Text color="#8f6f7c">    {choice.description}</Text>
                    ) : null}
                </Box>
            ))}
        </Box>
    );
};

const CompactSetup = ({ spotifySetup, authSetup }: { spotifySetup: SpotifySetupState; authSetup: AuthSetupState }) => {
    if (authSetup && authSetup.provider === "apple_music") {
        return (
            <Box flexDirection="column" paddingX={1} paddingY={1} borderTop={true} borderStyle="single" borderColor={BORDER_BLUE}>
                <Text color="#fff4f6">{authSetup.title}</Text>
                <Text color="#bf98a7">{authSetup.message}</Text>
                {authSetup.providers && authSetup.providers.length > 0 ? (
                    <Text color="#9d7787">
                        Providers: {authSetup.providers.map((provider) => provider.value).join(" / ")}
                    </Text>
                ) : null}
                {authSetup.methods && authSetup.methods.length > 0 ? (
                    <Text color="#9d7787">
                        Methods: {authSetup.methods.map((method) => method.value).join(" / ")}
                    </Text>
                ) : null}
                {authSetup.active && authSetup.prompt ? (
                    <Text color="#9d7787">Input: {authSetup.prompt}</Text>
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
                <Text color="#9d7787">Input: {spotifySetup.prompt}</Text>
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
    minimal = false,
    switchHint = null,
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
    minimal?: boolean;
    switchHint?: string | null;
}) => {
    const selectedChoice = confirm?.choices[Math.min(confirmIndex, Math.max(0, confirm.choices.length - 1))] ?? null;
    const showInput = !confirm || Boolean(selectedChoice?.input);

    return (
        <Box flexDirection="column">
            {!minimal ? (
                <Box flexDirection="column" flexShrink={0} paddingX={1}>
                    <HelpPanel panel={helpPanel} selectedIndex={helpPanelIndex} />
                    <SlashCommandList suggestions={slashSuggestions} selectedIndex={slashIndex} />
                    <CompactConfirm confirm={confirm} confirmIndex={confirmIndex} />
                    <CompactSetup spotifySetup={spotifySetup} authSetup={authSetup} />
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

const MiniPlayerInputDock = ({
    input,
    setInput,
    onSubmit,
    inputPlaceholder,
    inputMask,
    inputFocus,
    inputRevision,
    confirm,
    confirmIndex,
    switchHint,
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
    switchHint: string;
}) => (
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
        spotifySetup={null}
        authSetup={null}
        slashSuggestions={[]}
        slashIndex={0}
        helpPanel={null}
        helpPanelIndex={0}
        minimal={true}
        switchHint={switchHint}
    />
);

const ConversationColumn = ({
    chatItems,
    statusText,
    elapsed,
    tokens,
    showRunMetrics,
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
    chatScrollOffset,
    onMaxChatScrollOffsetChange,
    fill = false,
}: {
    chatItems: ChatItem[];
    statusText: string;
    elapsed: string | null;
    tokens: string | null;
    showRunMetrics: boolean;
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
    chatScrollOffset: number;
    onMaxChatScrollOffsetChange: (value: number) => void;
    fill?: boolean;
}) => (
    <Box flexDirection="column" flexGrow={fill ? 1 : 0} flexShrink={1} minHeight={0} height={fill ? "100%" : undefined}>
        <ChatPane items={chatItems} scrollOffset={chatScrollOffset} onMaxScrollOffsetChange={onMaxChatScrollOffsetChange} fill={fill} />
        <Box paddingX={1} height={1} flexShrink={0}>
            <Text color="#bf98a7">
                {statusText}
                {showRunMetrics && (elapsed || tokens) ? (
                    <>
                        {elapsed ? (
                            <>
                                <Text color="#7f5d6b"> • </Text>
                                <Text color="#d8bcc7">{elapsed}</Text>
                            </>
                        ) : null}
                        {tokens ? (
                            <>
                                <Text color="#7f5d6b"> • </Text>
                                <Text color="#d8bcc7">{tokens}</Text>
                            </>
                        ) : null}
                    </>
                ) : null}
            </Text>
        </Box>
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
        />
    </Box>
);

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
        <Box width="100%" height="100%" padding={0} flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}
            borderStyle="single" borderColor={BORDER_BLUE}>
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
    statusText,
    elapsed,
    tokens,
    showRunMetrics,
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
    chatScrollOffset,
    onMaxChatScrollOffsetChange,
}: {
    chatItems: ChatItem[];
    statusText: string;
    elapsed: string | null;
    tokens: string | null;
    showRunMetrics: boolean;
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
    chatScrollOffset: number;
    onMaxChatScrollOffsetChange: (value: number) => void;
}) => (
    <Box width="100%" height="100%" flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
        <ConversationColumn
            chatItems={chatItems}
            statusText={statusText}
            elapsed={elapsed}
            tokens={tokens}
            showRunMetrics={showRunMetrics}
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
            chatScrollOffset={chatScrollOffset}
            onMaxChatScrollOffsetChange={onMaxChatScrollOffsetChange}
            fill={true}
        />
    </Box>
);

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
    elapsed,
    tokens,
    showRunMetrics,
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
    activeRegion,
    miniSnapshotRevision,
    miniLayout,
    chatScrollOffset,
    onMaxChatScrollOffsetChange,
    terminalSpace,
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
    elapsed: string | null;
    tokens: string | null;
    showRunMetrics: boolean;
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
    activeRegion: ShellRegion;
    miniSnapshotRevision: number;
    miniLayout: MiniPlayerLayout;
    chatScrollOffset: number;
    onMaxChatScrollOffsetChange: (value: number) => void;
    terminalSpace: TerminalSpace;
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
            elapsed={elapsed}
            tokens={tokens}
            showRunMetrics={showRunMetrics}
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
            chatScrollOffset={chatScrollOffset}
            onMaxChatScrollOffsetChange={onMaxChatScrollOffsetChange}
        />
    );
};

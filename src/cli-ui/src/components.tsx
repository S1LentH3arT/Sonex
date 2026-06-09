import React from 'react';
import { Box, Text, measureElement } from 'ink';
import TextInput from 'ink-text-input';
import { APP_TIP_PLACEHOLDER, APP_VERSION, BORDER_BLUE, BORDER_BLUE_SOFT, FALLBACK_MODEL_NAME, MAX_VISIBLE_MODEL_CHOICES, MAX_VISIBLE_SLASH_COMMANDS, SONEX_MASCOT } from './constants.js';
import { HELP_PANEL_VISIBLE_COMMANDS, helpPanelCommands, visibleCommandWindow } from './command-panel.js';
import { buildProgressBar, formatDuration } from './format.js';
import { getVisibleChatWindow } from './chat-window.js';
import { isHttpCoverSource, useCoverArt, usePlaybackProgress } from './hooks.js';
import { coverVisualFromSource, type CoverVisualModel } from './cover-visual.js';
import { chooseCoverPatternVariant, renderCoverPatternHalfBlocks, type CoverPatternPayload, type TerminalSpace } from './cover-pattern.js';
import { resolveMiniPlayerChrome, type ShellLayout, type SmallPlaybackFocus } from './layout.js';
import type { ActivityItem, ActivityKind, AuthMethodChoice, AuthRuntimeState, AuthSetupState, ChatBubbleProps, ChatItem, ConfirmState, HelpPanelState, LoginScreenProps, PlayerPaneVariant, PlayerState, PromptInputProps, SlashCommandSuggestion, SpotifySetupState, TrackSummary } from './types.js';

/**
 * Defines the mascot function.
 *
 * Implements the mascot behavior used by components.tsx.
 * @returns The computed result for the surrounding CLI UI flow.
 */
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

/**
 * Defines the format auth label function.
 *
 * Implements the format auth label behavior used by components.tsx.
 *
 * @param state Input value used by the format auth label operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
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

/**
 * Defines the header frame function.
 *
 * Implements the header frame behavior used by components.tsx.
 *
 * @param authState Input value used by the header frame operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export const HeaderFrame = ({ authState }: { authState: AuthRuntimeState }) => (
    <Box width="100%" minHeight={5} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE}>
        <Mascot />
        <Box flexDirection="column" justifyContent="flex-start">
            <Text><Text bold color="#fff4f6">Sonex CLI</Text> <Text color="#bf98a7">v{APP_VERSION}</Text></Text>
            <Text><Text color="#d8bcc7">{authState.model || authState.provider || FALLBACK_MODEL_NAME}</Text> <Text color="#9d7787">•</Text> <Text color="#d8bcc7">{formatAuthLabel(authState)}</Text></Text>
            <Text color="#bf98a7">~/dev/sonex</Text>
            <Text color={BORDER_BLUE_SOFT}>{APP_TIP_PLACEHOLDER}</Text>
        </Box>
    </Box>
);

/**
 * Defines the is generic auth setup function.
 *
 * Implements the is generic auth setup behavior used by components.tsx.
 *
 * @param setup Input value used by the is generic auth setup operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export const isGenericAuthSetup = (setup: AuthSetupState): boolean => {
    if (!setup?.active) return false;
    return setup.provider !== "apple_music";
};

/**
 * Defines the login choice list function.
 *
 * Implements the login choice list behavior used by components.tsx.
 *
 * @param choices,selectedIndex,visibleLimit Input value used by the login choice list operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const LoginChoiceList = ({ choices, selectedIndex, visibleLimit }: {
    choices: AuthMethodChoice[];
    selectedIndex: number;
    visibleLimit?: number;
}) => {
    /**
     * Defines the bounded index constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const boundedIndex = Math.min(Math.max(selectedIndex, 0), Math.max(0, choices.length - 1));
    /**
     * Defines the limit constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const limit = Math.min(visibleLimit ?? choices.length, choices.length);
    /**
     * Defines the max start constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const maxStart = Math.max(0, choices.length - limit);
    /**
     * Defines the start index constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const startIndex = Math.min(Math.max(0, boundedIndex - limit + 1), maxStart);
    /**
     * Defines the visible choices constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const visibleChoices = choices.slice(startIndex, startIndex + limit);

    return (
        <Box flexDirection="column" marginTop={1}>
            {visibleChoices.map((choice, index) => {
                /**
                 * Defines the absolute index constant.
                 *
                 * Stores stable configuration or display data consumed by components.tsx.
                 */
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

/**
 * Defines the login screen function.
 *
 * Implements the login screen behavior used by components.tsx.
 *
 * @param authSetup,selectedIndex,apiKeyInput,setApiKeyInput,onApiKeySubmit, Input value used by the login screen operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export const LoginScreen = ({
    authSetup,
    selectedIndex,
    apiKeyInput,
    setApiKeyInput,
    onApiKeySubmit,
}: LoginScreenProps) => {
    if (!authSetup) return null;

    /**
     * Defines the provider choices constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const providerChoices = authSetup.providers ?? [];
    /**
     * Defines the method choices constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const methodChoices = authSetup.methods ?? [];
    /**
     * Defines the is provider step constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const isProviderStep = authSetup.step === "provider";
    /**
     * Defines the is method step constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const isMethodStep = authSetup.step === "method";
    /**
     * Defines the model choices constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const modelChoices = authSetup.models ?? [];
    /**
     * Defines the is api key step constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const isApiKeyStep = authSetup.step === "api_key";
    /**
     * Defines the is model step constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const isModelStep = authSetup.step === "model";
    /**
     * Defines the is oauth wait constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const isOauthWait = authSetup.step === "oauth_wait";
    /**
     * Defines the choices constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const choices = isProviderStep ? providerChoices : isMethodStep ? methodChoices : isModelStep ? modelChoices : [];
    /**
     * Defines the display message constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
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

/**
 * Defines the prompt input function.
 *
 * Implements the prompt input behavior used by components.tsx.
 *
 * @param input,setInput,onSubmit,focus,placeholder,mask,inputRevision Input value used by the prompt input operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
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

/**
 * Defines the slash command list function.
 *
 * Implements the slash command list behavior used by components.tsx.
 *
 * @param suggestions,selectedIndex Input value used by the slash command list operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const SlashCommandList = ({ suggestions, selectedIndex }: {
    suggestions: SlashCommandSuggestion[];
    selectedIndex: number;
}) => {
    if (suggestions.length === 0) return null;

    /**
     * Defines the {items: visible suggestions, bounded index, start index} constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const { items: visibleSuggestions, boundedIndex, startIndex } = visibleCommandWindow(
        suggestions,
        selectedIndex,
        MAX_VISIBLE_SLASH_COMMANDS,
    );

    return (
        <Box flexDirection="column" paddingX={1}>
            {visibleSuggestions.map((command, index) => {
                /**
                 * Defines the absolute index constant.
                 *
                 * Stores stable configuration or display data consumed by components.tsx.
                 */
                const absoluteIndex = startIndex + index;
                /**
                 * Defines the command color constant.
                 *
                 * Stores stable configuration or display data consumed by components.tsx.
                 */
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

/**
 * Defines the help panel function.
 *
 * Implements the help panel behavior used by components.tsx.
 *
 * @param panel,selectedIndex Input value used by the help panel operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const HelpPanel = ({ panel, selectedIndex }: { panel: HelpPanelState; selectedIndex: number }) => {
    if (!panel) return null;
    /**
     * Defines the commands constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const commands = helpPanelCommands(panel.commands);
    /**
     * Defines the {items: visible commands, bounded index, start index} constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
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
                /**
                 * Defines the absolute index constant.
                 *
                 * Stores stable configuration or display data consumed by components.tsx.
                 */
                const absoluteIndex = startIndex + index;
                /**
                 * Defines the command color constant.
                 *
                 * Stores stable configuration or display data consumed by components.tsx.
                 */
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

/**
 * Defines the chat bubble function.
 *
 * Implements the chat bubble behavior used by components.tsx.
 *
 * @param role,content Input value used by the chat bubble operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const ChatBubble = ({ role, content }: ChatBubbleProps) => {
    /**
     * Defines the is user constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const isUser = role === "user";
    /**
     * Defines the color constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const color = isUser ? "#fff6f8" : "#f6e9ee";
    /**
     * Defines the border left color constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const borderLeftColor = isUser ? BORDER_BLUE : BORDER_BLUE_SOFT;

    return (
        <Box paddingX={2} marginBottom={1} borderStyle="single" borderTop={false} borderRight={false}
            borderBottom={false} borderLeft={true} borderColor={borderLeftColor} flexDirection="column" width="100%">
            <Text color={color}>{content}</Text>
        </Box>
    );
};

/**
 * Defines the chat pane function.
 *
 * Implements the chat pane behavior used by components.tsx.
 *
 * @param items,scrollOffset,onMaxScrollOffsetChange,fill=false Input value used by the chat pane operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const ChatPane = ({ items, scrollOffset, onMaxScrollOffsetChange, fill = false }: {
    items: ChatItem[];
    scrollOffset: number;
    onMaxScrollOffsetChange: (value: number) => void;
    fill?: boolean;
}) => {
    /**
     * Defines the container ref constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const containerRef = React.useRef<any>(null);
    /**
     * Defines the [viewport rows, set viewport rows] constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const [viewportRows, setViewportRows] = React.useState(12);
    /**
     * Defines the visible window constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const visibleWindow = React.useMemo(
        () => getVisibleChatWindow(items, viewportRows, scrollOffset),
        [items, scrollOffset, viewportRows],
    );

    React.useEffect(() => {
        if (!containerRef.current) return;
        /**
         * Defines the {height} constant.
         *
         * Stores stable configuration or display data consumed by components.tsx.
         */
        const { height } = measureElement(containerRef.current);
        if (height > 0 && height !== viewportRows) {
            setViewportRows(height);
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

/**
 * Defines the queue pane function.
 *
 * Implements the queue pane behavior used by components.tsx.
 *
 * @param tracks Input value used by the queue pane operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
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
                /**
                 * Defines the marker constant.
                 *
                 * Stores stable configuration or display data consumed by components.tsx.
                 */
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

/**
 * Defines the search results pane function.
 *
 * Implements the search results pane behavior used by components.tsx.
 *
 * @param tracks Input value used by the search results pane operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
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
                /**
                 * Defines the marker constant.
                 *
                 * Stores stable configuration or display data consumed by components.tsx.
                 */
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

/**
 * Defines the activity pane function.
 *
 * Implements the activity pane behavior used by components.tsx.
 *
 * @param items,confirm,confirmIndex,spotifySetup,authSetup Input value used by the activity pane operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const ActivityPane = ({ items, confirm, confirmIndex, spotifySetup, authSetup }: {
    items: ActivityItem[];
    confirm: ConfirmState;
    confirmIndex: number;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
}) => {
    /**
     * Defines the colors constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
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
                        /**
                         * Defines the status color constant.
                         *
                         * Stores stable configuration or display data consumed by components.tsx.
                         */
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

/**
 * Defines the cover atmosphere function.
 *
 * Implements the cover atmosphere behavior used by components.tsx.
 *
 * @param visual,art,compact Input value used by the cover atmosphere operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const CoverAtmosphere = ({ visual, art, compact }: {
    visual: CoverVisualModel;
    art: string | null;
    compact: boolean;
}) => {
    if (!compact && art) {
        return <Text>{art}</Text>;
    }

    /**
     * Defines the rows constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const rows = compact ? visual.blocks.slice(0, 5) : visual.blocks;
    /**
     * Defines the columns constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
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

/**
 * Defines the cover pattern art constant.
 *
 * Stores stable configuration or display data consumed by components.tsx.
 */
const CoverPatternArt = React.memo(({ pattern, space, maxSize }: {
    pattern: CoverPatternPayload;
    space: TerminalSpace;
    maxSize?: 32 | 48 | 64;
}) => {
    /**
     * Defines the variant constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const variant = React.useMemo(
        () => chooseCoverPatternVariant(pattern, space, maxSize ? { maxSize } : undefined),
        [pattern, space, maxSize],
    );
    /**
     * Defines the rows constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const rows = React.useMemo(() => renderCoverPatternHalfBlocks(variant?.grid ?? [], pattern.palette), [variant, pattern.palette]);

    if (!variant) return null;
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

/**
 * Defines the static cover constant.
 *
 * Stores stable configuration or display data consumed by components.tsx.
 */
const StaticCover = React.memo(({ visual, coverUrl, coverPattern, terminalSpace, compact }: {
    visual: CoverVisualModel;
    coverUrl: string | null;
    coverPattern: CoverPatternPayload | null;
    terminalSpace?: TerminalSpace;
    compact: boolean;
}) => {
    /**
     * Defines the max size constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const maxSize = compact ? 48 : 32;
    /**
     * Defines the chosen pattern constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const chosenPattern = coverPattern && terminalSpace
        ? chooseCoverPatternVariant(coverPattern, terminalSpace, { maxSize })
        : null;
    /**
     * Defines the has cover pattern constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const hasCoverPattern = Boolean(coverPattern && terminalSpace && chosenPattern);
    /**
     * Defines the compact cover width constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const compactCoverWidth = Math.max(22, Math.min(48, (terminalSpace?.columns ?? 40) - 6));
    /**
     * Defines the compact cover height constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const compactCoverHeight = Math.max(8, Math.min(24, (terminalSpace?.rows ?? 22) - 8));
    /**
     * Defines the fetchable cover url constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const fetchableCoverUrl = !hasCoverPattern && isHttpCoverSource(coverUrl) ? coverUrl : null;
    /**
     * Defines the {art, failed} constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const { art, failed } = useCoverArt(fetchableCoverUrl, compact ? compactCoverWidth : 32, compact ? compactCoverHeight : 16);
    /**
     * Defines the resolved visual constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const resolvedVisual = React.useMemo(() => coverVisualFromSource(coverUrl, failed), [coverUrl, failed]);
    /**
     * Defines the pattern requested at constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
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

    if (hasCoverPattern && coverPattern && terminalSpace) {
        return (
            <Box flexGrow={compact ? 1 : 0} flexShrink={1} minHeight={compact ? compactCoverHeight : undefined} alignItems="center" justifyContent="center">
                <CoverPatternArt pattern={coverPattern} space={terminalSpace} maxSize={maxSize} />
            </Box>
        );
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

/**
 * Defines the player mascot function.
 *
 * Implements the player mascot behavior used by components.tsx.
 *
 * @param visual,frame,compact Input value used by the player mascot operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const PlayerMascot = ({ visual, frame, compact }: {
    visual: CoverVisualModel;
    frame: number;
    compact: boolean;
}) => {
    /**
     * Defines the pulse constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const pulse = ["▁", "▃", "▅", "▃"];
    /**
     * Defines the left constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const left = pulse[frame] ?? "▁";
    /**
     * Defines the right constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
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

    /**
     * Defines the lift constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
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

/**
 * Defines the track details constant.
 *
 * Stores stable configuration or display data consumed by components.tsx.
 */
const TrackDetails = React.memo(({ player, compact }: { player: PlayerState; compact: boolean }) => (
    <Box flexDirection="column">
        <Text bold color="#fff4f6">{player.name}</Text>
        <Text color="#bf98a7">{player.artist}</Text>
        {!compact || player.album !== "-" ? <Text color="#bf98a7">{player.album}</Text> : null}
    </Box>
));

/**
 * Defines the mini track details constant.
 *
 * Stores stable configuration or display data consumed by components.tsx.
 */
const MiniTrackDetails = React.memo(({ name, artist, album }: { name: string; artist: string; album: string }) => (
    <Box flexDirection="column">
        <Text bold color="#fff4f6">{name}</Text>
        <Text color="#bf98a7">{artist}</Text>
        {album !== "-" ? <Text color="#bf98a7">{album}</Text> : null}
    </Box>
));

/**
 * Defines the playback progress time constant.
 *
 * Stores stable configuration or display data consumed by components.tsx.
 */
const PlaybackProgressTime = React.memo(({ player, active }: { player: PlayerState; active: boolean }) => {
    /**
     * Defines the progress ms constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const progressMs = usePlaybackProgress(player, active);
    return <Text color="#bf98a7">{formatDuration(progressMs)}</Text>;
});

/**
 * Defines the mini playback meter constant.
 *
 * Stores stable configuration or display data consumed by components.tsx.
 */
const MiniPlaybackMeter = React.memo(({ player, visual }: {
    player: PlayerState;
    visual: CoverVisualModel;
}) => {
    /**
     * Defines the progress ms constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const progressMs = player.progress_ms ?? 0;
    /**
     * Defines the duration constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const duration = formatDuration(player.duration_ms);
    /**
     * Defines the progress bar constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const progressBar = buildProgressBar(progressMs, player.duration_ms, 14);

    return (
        <Box flexDirection="column" marginTop={1}>
            <Text>
                <Text color="#bf98a7">{formatDuration(progressMs)}</Text> <Text color={visual.secondary}>{progressBar}</Text> <Text color="#bf98a7">{duration}</Text>
            </Text>
        </Box>
    );
});

/**
 * Defines the mini player static body constant.
 *
 * Stores stable configuration or display data consumed by components.tsx.
 */
const MiniPlayerStaticBody = React.memo(({
    name,
    artist,
    album,
    visual,
    coverUrl,
    coverPattern,
    terminalSpace,
}: {
    name: string;
    artist: string;
    album: string;
    visual: CoverVisualModel;
    coverUrl: string | null;
    coverPattern: CoverPatternPayload | null;
    terminalSpace?: TerminalSpace;
}) => (
    <>
        <StaticCover visual={visual} coverUrl={coverUrl} coverPattern={coverPattern} terminalSpace={terminalSpace} compact={true} />
        <Box flexDirection="column" marginTop={1} flexShrink={0}>
            <MiniTrackDetails name={name} artist={artist} album={album} />
        </Box>
    </>
), (prev, next) => (
    prev.name === next.name
    && prev.artist === next.artist
    && prev.album === next.album
    && prev.visual === next.visual
    && prev.coverUrl === next.coverUrl
    && prev.coverPattern === next.coverPattern
    && prev.terminalSpace === next.terminalSpace
));

/**
 * Defines the playback meter function.
 *
 * Implements the playback meter behavior used by components.tsx.
 *
 * @param player,visual,compact=false,active=true Input value used by the playback meter operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const PlaybackMeter = ({ player, visual, compact = false, active = true }: {
    player: PlayerState;
    visual: CoverVisualModel;
    compact?: boolean;
    active?: boolean;
}) => {
    if (compact) {
        return <MiniPlaybackMeter player={player} visual={visual} />;
    }

    /**
     * Defines the progress ms constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const progressMs = usePlaybackProgress(player, active);
    /**
     * Defines the progress constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const progress = formatDuration(progressMs);
    /**
     * Defines the duration constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const duration = formatDuration(player.duration_ms);
    /**
     * Defines the progress bar constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const progressBar = buildProgressBar(progressMs, player.duration_ms, 18);
    /**
     * Defines the is playing constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const isPlaying = player.is_playing === true;
    return (
        <Box flexDirection="column" marginTop={1}>
            <Text>
                <Text color="#bf98a7">{progress}</Text> <Text color={visual.secondary}>{progressBar}</Text> <Text color="#bf98a7">{duration}</Text>
            </Text>
            <Text color={isPlaying ? visual.accent : "#7f5d6b"}>{isPlaying ? "playing" : "paused"}</Text>
        </Box>
    );
};

/**
 * Defines the player pane function.
 *
 * Implements the player pane behavior used by components.tsx.
 *
 * @param player,coverUrl,coverPattern,terminalSpace,variant="full",active=true Input value used by the player pane operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const PlayerPane = ({ player, coverUrl, coverPattern, terminalSpace, variant = "full", active = true }: {
    player: PlayerState,
    coverUrl: string | null,
    coverPattern?: CoverPatternPayload | null,
    terminalSpace?: TerminalSpace,
    variant?: PlayerPaneVariant,
    active?: boolean
}) => {
    /**
     * Defines the compact constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const compact = variant === "compact";
    /**
     * Defines the visual constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const visual = React.useMemo(() => coverVisualFromSource(coverUrl, false), [coverUrl]);

    if (compact) {
        return (
            <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={8} padding={1} paddingX={1}>
                <MiniPlayerStaticBody
                    name={player.name}
                    artist={player.artist}
                    album={player.album}
                    visual={visual}
                    coverUrl={coverUrl}
                    coverPattern={coverPattern ?? null}
                    terminalSpace={terminalSpace}
                />
                <PlaybackMeter player={player} visual={visual} compact={compact} active={active} />
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

/**
 * Defines the compact conversation function.
 *
 * Implements the compact conversation behavior used by components.tsx.
 *
 * @param items,statusText Input value used by the compact conversation operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
const CompactConversation = ({ items, statusText }: { items: ChatItem[]; statusText: string }) => {
    /**
     * Defines the visible items constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
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

/**
 * Defines the compact confirm function.
 *
 * Implements the compact confirm behavior used by components.tsx.
 *
 * @param confirm,confirmIndex Input value used by the compact confirm operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
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

/**
 * Defines the compact setup function.
 *
 * Implements the compact setup behavior used by components.tsx.
 *
 * @param spotifySetup,authSetup Input value used by the compact setup operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
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

/**
 * Defines the input dock function.
 *
 * Implements the input dock behavior used by components.tsx.
 *
 * @param input,setInput,onSubmit,inputPlaceholder,inputMask,inputFocus,inputRevision,confirm,confirmIndex,spotifySetup,authSetup,slashSuggestions,slashIndex,helpPanel,helpPanelIndex,minimal=false,switchHint=null, Input value used by the input dock operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
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
    /**
     * Defines the selected choice constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const selectedChoice = confirm?.choices[Math.min(confirmIndex, Math.max(0, confirm.choices.length - 1))] ?? null;
    /**
     * Defines the show input constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
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

/**
 * Defines the mini player input dock function.
 *
 * Implements the mini player input dock behavior used by components.tsx.
 *
 * @param input,setInput,onSubmit,inputPlaceholder,inputMask,inputFocus,inputRevision,confirm,confirmIndex,switchHint, Input value used by the mini player input dock operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
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

/**
 * Defines the conversation column function.
 *
 * Implements the conversation column behavior used by components.tsx.
 *
 * @param chatItems,statusText,elapsed,tokens,showRunMetrics,input,setInput,onSubmit,inputPlaceholder,inputMask,inputFocus,inputRevision,confirm,confirmIndex,spotifySetup,authSetup,slashSuggestions,slashIndex,helpPanel,helpPanelIndex,chatScrollOffset,onMaxChatScrollOffsetChange,fill=false, Input value used by the conversation column operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
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
 * Use visible snapshot.
 *
 * Coordinates the use visible snapshot operation for the CLI UI runtime.
 *
 * @param value Input value used by the use visible snapshot operation.
 * @param active Input value used by the use visible snapshot operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function useVisibleSnapshot<T>(value: T, active: boolean): T {
    /**
     * Defines the snapshot ref constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const snapshotRef = React.useRef(value);
    if (active) {
        snapshotRef.current = value;
        return value;
    }
    return snapshotRef.current;
}

/**
 * Use visible snapshot on revision.
 *
 * Coordinates the use visible snapshot on revision operation for the CLI UI runtime.
 *
 * @param value Input value used by the use visible snapshot on revision operation.
 * @param active Input value used by the use visible snapshot on revision operation.
 * @param snapshotRevision Input value used by the use visible snapshot on revision operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
function useVisibleSnapshotOnRevision<T>(value: T, active: boolean, snapshotRevision: number): T {
    /**
     * Defines the snapshot ref constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const snapshotRef = React.useRef(value);
    /**
     * Defines the revision ref constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
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

/**
 * Defines the dynamic shell function.
 *
 * Implements the dynamic shell behavior used by components.tsx.
 *
 * @param input,setInput,onSubmit,inputPlaceholder,inputMask,inputFocus,inputRevision,chatItems,queueItems,player,statusText,elapsed,tokens,showRunMetrics,coverUrl,coverPattern,confirm,confirmIndex,spotifySetup,authSetup,slashSuggestions,slashIndex,helpPanel,helpPanelIndex,layout,layoutPulse,miniSnapshotRevision,smallPlaybackFocus,chatScrollOffset,onMaxChatScrollOffsetChange,terminalSpace, Input value used by the dynamic shell operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export const DynamicShell = ({
    input,
    setInput,
    onSubmit,
    inputPlaceholder,
    inputMask,
    inputFocus,
    inputRevision,
    chatItems,
    queueItems,
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
    layout,
    layoutPulse,
    miniSnapshotRevision,
    smallPlaybackFocus,
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
    queueItems: Array<{ index: string; title: string; artist: string; duration: string }>;
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
    layout: ShellLayout;
    layoutPulse: boolean;
    miniSnapshotRevision: number;
    smallPlaybackFocus: SmallPlaybackFocus;
    chatScrollOffset: number;
    onMaxChatScrollOffsetChange: (value: number) => void;
    terminalSpace: TerminalSpace;
}) => {
    /**
     * Defines the show playback sidebar constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const showPlaybackSidebar = layout === "full";
    /**
     * Defines the mini visible constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const miniVisible = layout === "miniPlayer";
    /**
     * Defines the chat visible constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const chatVisible = layout !== "miniPlayer";
    /**
     * Defines the mini chrome constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const miniChrome = resolveMiniPlayerChrome({ layout, smallPlaybackFocus });
    /**
     * Defines the conversation status text constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const conversationStatusText = layout === "chat" && player.is_playing
        ? `${statusText} · ${miniChrome.switchHint}`
        : statusText;
    /**
     * Defines the mini snapshot constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const miniSnapshot = useVisibleSnapshotOnRevision({
        player,
        coverUrl,
        coverPattern,
        terminalSpace,
        switchHint: miniChrome.switchHint,
    }, miniVisible, miniSnapshotRevision);
    /**
     * Defines the chat snapshot constant.
     *
     * Stores stable configuration or display data consumed by components.tsx.
     */
    const chatSnapshot = useVisibleSnapshot({
        chatItems,
        statusText: conversationStatusText,
        elapsed,
        tokens,
        showRunMetrics,
        input,
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
        queueItems,
        player,
        coverUrl,
        coverPattern,
        terminalSpace,
    }, chatVisible);

    return (
        <Box width="100%" flexDirection="column" flexGrow={showPlaybackSidebar || miniVisible ? 1 : 0} flexShrink={1} minHeight={0}>
            <Box display={miniVisible ? "flex" : "none"} width="100%" height="100%" paddingX={1} flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}
                borderStyle="single" borderColor={layoutPulse ? "#f3b2c6" : BORDER_BLUE}>
                <Box flexGrow={1} flexShrink={1} minHeight={0} borderBottom={true} borderStyle="single" borderColor={layoutPulse ? "#f3b2c6" : BORDER_BLUE}>
                    <PlayerPane
                        player={miniSnapshot.player}
                        coverUrl={miniSnapshot.coverUrl}
                        coverPattern={miniSnapshot.coverPattern}
                        terminalSpace={miniSnapshot.terminalSpace}
                        variant="compact"
                        active={miniVisible}
                    />
                </Box>
            </Box>

            <Box display={chatVisible ? "flex" : "none"} width="100%" flexDirection={showPlaybackSidebar ? "row" : "column"} flexGrow={showPlaybackSidebar ? 1 : 0} flexShrink={1} minHeight={0}>
                <Box width={showPlaybackSidebar ? "45%" : "100%"} minWidth={showPlaybackSidebar ? 48 : undefined} flexDirection="column" flexGrow={showPlaybackSidebar ? 1 : 0} flexShrink={1} minHeight={0}>
                    <ConversationColumn
                        chatItems={chatSnapshot.chatItems}
                        statusText={chatSnapshot.statusText}
                        elapsed={chatSnapshot.elapsed}
                        tokens={chatSnapshot.tokens}
                        showRunMetrics={chatSnapshot.showRunMetrics}
                        input={chatSnapshot.input}
                        setInput={setInput}
                        onSubmit={onSubmit}
                        inputPlaceholder={chatSnapshot.inputPlaceholder}
                        inputMask={chatSnapshot.inputMask}
                        inputFocus={chatSnapshot.inputFocus && chatVisible}
                        inputRevision={chatSnapshot.inputRevision}
                        confirm={chatSnapshot.confirm}
                        confirmIndex={chatSnapshot.confirmIndex}
                        spotifySetup={chatSnapshot.spotifySetup}
                        authSetup={chatSnapshot.authSetup}
                        slashSuggestions={chatSnapshot.slashSuggestions}
                        slashIndex={chatSnapshot.slashIndex}
                        helpPanel={chatSnapshot.helpPanel}
                        helpPanelIndex={chatSnapshot.helpPanelIndex}
                        chatScrollOffset={chatSnapshot.chatScrollOffset}
                        onMaxChatScrollOffsetChange={onMaxChatScrollOffsetChange}
                        fill={showPlaybackSidebar}
                    />
                </Box>

                <Box display={showPlaybackSidebar ? "flex" : "none"} width="55%" minWidth={62} height="100%" flexDirection="column" borderLeft={true} borderStyle="single" borderColor={layoutPulse ? "#f3b2c6" : BORDER_BLUE} flexGrow={1} flexShrink={0} minHeight={0}>
                    <QueuePane tracks={chatSnapshot.queueItems} />
                    <PlayerPane
                        player={chatSnapshot.player}
                        coverUrl={chatSnapshot.coverUrl}
                        coverPattern={chatSnapshot.coverPattern}
                        terminalSpace={chatSnapshot.terminalSpace}
                        active={showPlaybackSidebar}
                    />
                </Box>
            </Box>
        </Box>
    );
};

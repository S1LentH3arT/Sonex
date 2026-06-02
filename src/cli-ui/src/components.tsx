import React from 'react';
import {Box, Text, measureElement} from 'ink';
import TextInput from 'ink-text-input';
import {APP_TIP_PLACEHOLDER, APP_VERSION, BORDER_BLUE, BORDER_BLUE_SOFT, FALLBACK_MODEL_NAME, MAX_VISIBLE_MODEL_CHOICES, MAX_VISIBLE_SLASH_COMMANDS, SONEX_MASCOT} from './constants.js';
import {buildProgressBar, formatDuration} from './format.js';
import {getVisibleChatWindow} from './chat-window.js';
import {useCoverArt, usePlaybackProgress} from './hooks.js';
import type {ActivityItem, ActivityKind, AuthMethodChoice, AuthRuntimeState, AuthSetupState, ChatBubbleProps, ChatItem, ConfirmState, HelpPanelState, LoginScreenProps, PlayerPaneVariant, PlayerState, PromptInputProps, SlashCommandSuggestion, SpotifySetupState, TrackSummary} from './types.js';

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

export const HeaderFrame = ({authState}: {authState: AuthRuntimeState}) => (
    <Box width={74} minHeight={5} paddingX={1} borderStyle="single" borderColor={BORDER_BLUE}>
        <Mascot/>
        <Box flexDirection="column" justifyContent="flex-start">
            <Text><Text bold color="#fff4f6">Sonex CLI</Text> <Text color="#bf98a7">v{APP_VERSION}</Text></Text>
            <Text><Text color="#d8bcc7">{authState.model || authState.provider || FALLBACK_MODEL_NAME}</Text> <Text color="#9d7787">•</Text> <Text color="#d8bcc7">{formatAuthLabel(authState)}</Text></Text>
            <Text color="#bf98a7">~/dev/sonex</Text>
            <Text color={BORDER_BLUE_SOFT}>{APP_TIP_PLACEHOLDER}</Text>
        </Box>
    </Box>
);

export const isGenericAuthSetup = (setup: AuthSetupState): boolean => {
    if (!setup?.active) return false;
    return setup.provider !== "apple_music";
};

const LoginChoiceList = ({choices, selectedIndex, visibleLimit}: {
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
    authState,
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
            <Box>
                <Mascot/>
                <Box flexDirection="column" justifyContent="flex-start">
                    <Text><Text bold color="#fff4f6">Sonex CLI</Text> <Text color="#bf98a7">v{APP_VERSION}</Text></Text>
                    <Text><Text color="#d8bcc7">{authState.model || authState.provider || FALLBACK_MODEL_NAME}</Text> <Text color="#9d7787">•</Text> <Text color="#d8bcc7">{formatAuthLabel(authState)}</Text></Text>
                    <Text color="#bf98a7">~/dev/sonex</Text>
                    <Text color={BORDER_BLUE_SOFT}>{APP_TIP_PLACEHOLDER}</Text>
                </Box>
            </Box>

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

const PromptInput = ({input, setInput, onSubmit, focus, placeholder, mask, inputRevision}: PromptInputProps) => (
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

const SlashCommandList = ({suggestions, selectedIndex}: {
    suggestions: SlashCommandSuggestion[];
    selectedIndex: number;
}) => {
    if (suggestions.length === 0) return null;

    const boundedIndex = Math.min(Math.max(selectedIndex, 0), suggestions.length - 1);
    const maxStart = Math.max(0, suggestions.length - MAX_VISIBLE_SLASH_COMMANDS);
    const startIndex = Math.min(
        Math.max(0, boundedIndex - MAX_VISIBLE_SLASH_COMMANDS + 1),
        maxStart,
    );
    const visibleSuggestions = suggestions.slice(startIndex, startIndex + MAX_VISIBLE_SLASH_COMMANDS);

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

const HelpPanel = ({panel}: {panel: HelpPanelState}) => {
    if (!panel) return null;

    return (
        <Box flexDirection="column" paddingX={1} paddingBottom={1}>
            <Text>
                <Text bold color="#fff4f6">{panel.title}</Text>
                <Text color="#7f5d6b"> - </Text>
                <Text color="#9d7787">{panel.hint}</Text>
            </Text>
            {panel.commands.length === 0 ? (
                <Text color="#7f5d6b">No matching commands.</Text>
            ) : panel.commands.map((command) => (
                <Text key={command.name}>
                    <Text color="#7f5d6b">  </Text>
                    <Text color="#bf98a7">{command.usage}</Text>
                    <Text color="#7f5d6b"> - </Text>
                    <Text color="#9d7787">{command.description}</Text>
                </Text>
            ))}
        </Box>
    );
};

const ChatBubble = ({role, content}: ChatBubbleProps) => {
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

const ChatPane = ({items, scrollOffset, onMaxScrollOffsetChange}: {
    items: ChatItem[];
    scrollOffset: number;
    onMaxScrollOffsetChange: (value: number) => void;
}) => {
    const containerRef = React.useRef<any>(null);
    const [viewportRows, setViewportRows] = React.useState(12);
    const visibleWindow = React.useMemo(
        () => getVisibleChatWindow(items, viewportRows, scrollOffset),
        [items, scrollOffset, viewportRows],
    );

    React.useEffect(() => {
        if (!containerRef.current) return;
        const {height} = measureElement(containerRef.current);
        if (height > 0 && height !== viewportRows) {
            setViewportRows(height);
        }
    });

    React.useEffect(() => {
        onMaxScrollOffsetChange(visibleWindow.maxScrollOffset);
    }, [onMaxScrollOffsetChange, visibleWindow.maxScrollOffset]);

    return (
        <Box ref={containerRef} flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} overflowY="hidden" paddingX={1}>
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
                            <ChatBubble key={`${items.indexOf(chat)}_${idx}`} role={chat.role} content={chat.content}/>
                        ))}
                        {visibleWindow.hasHiddenBelow ? <Text color="#7f5d6b">↓ newer messages</Text> : null}
                    </>
                )}
            </Box>
        </Box>
    );
};

const QueuePane = ({tracks}: { tracks: Array<{ index: string; title: string; artist: string; duration: string }> }) => (
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

const SearchResultsPane = ({tracks}: { tracks: TrackSummary[] }) => (
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

const ActivityPane = ({items, confirm, confirmIndex, spotifySetup, authSetup}: {
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
                            <Text key={choice.value} color={confirmIndex === idx ? "#fff4f6" : "#7f5d6b"}>
                                {confirmIndex === idx ? "> " : "  "}{choice.label}
                            </Text>
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

const PlayerPane = ({player, coverUrl, variant = "full"}: {
    player: PlayerState,
    coverUrl: string | null,
    variant?: PlayerPaneVariant
}) => {
    const compact = variant === "compact";
    const {art, failed} = useCoverArt(coverUrl, compact ? 14 : 32, compact ? 7 : 16);
    const duration = formatDuration(player.duration_ms);
    const progressMs = usePlaybackProgress(player);
    const progress = formatDuration(progressMs);
    const progressBar = buildProgressBar(progressMs, player.duration_ms, compact ? 14 : 18);

    return (
        <Box flexDirection="column" minHeight={compact ? 8 : 20} padding={1} paddingX={compact ? 1 : 2}>
            <Box marginBottom={compact ? 0 : 1}>
                <Text bold color="#f3b2c6">{compact ? "Playing" : "Now Playing"}</Text>
            </Box>
            <Box marginTop={compact ? 0 : 1}>
                {!compact && (
                    <Box width={36} paddingRight={2} flexDirection="column">
                        {art ? (
                            <Text>{art}</Text>
                        ) : coverUrl ? (
                            <Text color={failed ? "#ff9c9c" : "#7f5d6b"}>
                                {failed ? `Cover unavailable: ${coverUrl}` : "Loading cover..."}
                            </Text>
                        ) : (
                            <Text color="#7f5d6b">No cover art.</Text>
                        )}
                    </Box>
                )}
                {compact && art ? (
                    <Box width={18} paddingRight={1} flexDirection="column">
                        <Text>{art}</Text>
                    </Box>
                ) : null}
                <Box flexDirection="column" flexGrow={1} paddingTop={compact ? 0 : 1}>
                    <Text bold color="#fff4f6">{player.name}</Text>
                    <Text color="#bf98a7">{player.artist}</Text>
                    {!compact || player.album !== "-" ? <Text color="#bf98a7">{player.album}</Text> : null}
                    <Box marginTop={1}>
                        <Text>
                            <Text color="#bf98a7">{progress}</Text> <Text color="#7f5d6b">{progressBar}</Text> <Text
                            color="#bf98a7">{duration}</Text>
                        </Text>
                    </Box>
                </Box>
            </Box>
        </Box>
    );
};

const CompactConversation = ({items, statusText}: {items: ChatItem[]; statusText: string}) => {
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

const CompactConfirm = ({confirm, confirmIndex}: {confirm: ConfirmState; confirmIndex: number}) => {
    if (!confirm) return null;

    return (
        <Box flexDirection="column" paddingX={1} paddingY={1} borderTop={true} borderStyle="single" borderColor={BORDER_BLUE}>
            <Text color="#fff4f6">{confirm.message}</Text>
            {confirm.choices.map((choice, idx) => (
                <Text key={choice.value} color={confirmIndex === idx ? "#fff4f6" : "#7f5d6b"}>
                    {confirmIndex === idx ? "> " : "  "}{choice.label}
                </Text>
            ))}
        </Box>
    );
};

const CompactSetup = ({spotifySetup, authSetup}: {spotifySetup: SpotifySetupState; authSetup: AuthSetupState}) => {
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
}) => (
    <Box flexDirection="column">
        <Box flexDirection="column" flexShrink={0} paddingX={1}>
            <HelpPanel panel={helpPanel}/>
            <SlashCommandList suggestions={slashSuggestions} selectedIndex={slashIndex}/>
            <CompactConfirm confirm={confirm} confirmIndex={confirmIndex}/>
            <CompactSetup spotifySetup={spotifySetup} authSetup={authSetup}/>
        </Box>
        <Box borderTop={true} borderStyle="single" borderColor={BORDER_BLUE} paddingX={1} paddingTop={0} paddingBottom={1} flexDirection="row"
             minHeight={4} flexShrink={0}>
            <Text color="#7f5d6b">{"> "}</Text>
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
    chatScrollOffset: number;
    onMaxChatScrollOffsetChange: (value: number) => void;
}) => (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} height="100%">
        <ChatPane items={chatItems} scrollOffset={chatScrollOffset} onMaxScrollOffsetChange={onMaxChatScrollOffsetChange}/>
        <Box paddingX={1} height={1} flexShrink={0}>
            <Text color="#bf98a7">
                {statusText}
                {showRunMetrics && elapsed && tokens ? (
                    <>
                        <Text color="#7f5d6b"> • </Text>
                        <Text color="#d8bcc7">{elapsed}</Text>
                        <Text color="#7f5d6b"> • </Text>
                        <Text color="#d8bcc7">{tokens}</Text>
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
    queueItems,
    player,
    statusText,
    elapsed,
    tokens,
    showRunMetrics,
    coverUrl,
    confirm,
    confirmIndex,
    spotifySetup,
    authSetup,
    slashSuggestions,
    slashIndex,
    helpPanel,
    showPlaybackSidebar,
    chatScrollOffset,
    onMaxChatScrollOffsetChange,
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
    confirm: ConfirmState;
    confirmIndex: number;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
    slashSuggestions: SlashCommandSuggestion[];
    slashIndex: number;
    helpPanel: HelpPanelState;
    showPlaybackSidebar: boolean;
    chatScrollOffset: number;
    onMaxChatScrollOffsetChange: (value: number) => void;
}) => (
    <Box width="100%" height="100%" paddingX={1} flexDirection={showPlaybackSidebar ? "row" : "column"} flexGrow={1} flexShrink={1} minHeight={0}>
        <Box width={showPlaybackSidebar ? "45%" : 90} minWidth={showPlaybackSidebar ? 48 : undefined} flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
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
                chatScrollOffset={chatScrollOffset}
                onMaxChatScrollOffsetChange={onMaxChatScrollOffsetChange}
            />
        </Box>

        {showPlaybackSidebar ? (
            <Box width="55%" minWidth={62} flexDirection="column" borderLeft={true} borderStyle="single" borderColor={BORDER_BLUE} flexShrink={0}>
                <QueuePane tracks={queueItems}/>
                <PlayerPane player={player} coverUrl={coverUrl}/>
            </Box>
        ) : null}
    </Box>
);

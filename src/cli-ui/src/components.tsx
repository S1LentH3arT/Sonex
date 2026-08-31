import React from 'react';
import { Box, Static, Text, Transform, measureElement } from 'ink';
import TextInput from 'ink-text-input';
import stringWidth from 'string-width';
import { chatDocumentSegments } from './chat-document.js';
import { CHAT_SYSTEM_MARKER_COLOR, CHAT_USER_MARKER_COLOR, resolveChatContentColor, resolveChatMarkerColor, wrapChatMessageContent, wrapChatMessageSegments } from './chat-message.js';
import { resolveAgentChatTheme } from './chat-theme.js';
import { APP_VERSION, BORDER_BLUE, BORDER_BLUE_SOFT, FALLBACK_MODEL_NAME, MAX_VISIBLE_MODEL_CHOICES, MAX_VISIBLE_SLASH_COMMANDS, SONEX_MASCOT, SONEX_MASCOT_MICRO, SPOTIFY_GREEN, TOOL_NAVY, TOOL_VALUE } from './constants.js';
import { HELP_PANEL_VISIBLE_COMMANDS, helpPanelCommands, visibleCommandWindow } from './command-panel.js';
import { getVisibleConfirmChoices, resolveConfirmChoiceDisplayIndex } from './confirm-choice.js';
import { buildProgressBar, formatDuration, formatMiniTrackSubtitle, formatMusicCandidateDisplayLabel } from './format.js';
import { formatWorkingDirectory } from './info-banner.js';
import { isHttpCoverSource, useCoverArt } from './hooks.js';
import { hideInputCursor, INPUT_CURSOR_BLINK_INTERVAL_MS } from './input-cursor.js';
import { languageLabel, t } from './i18n.js';
import { coverVisualFromSource, type CoverVisualModel } from './cover-visual.js';
import { renderCoverPatternHalfBlocks, resolveCoverPatternDisplay, type CoverPatternPayload, type CoverPatternVariant, type TerminalSpace } from './cover-pattern.js';
import { resolveMiniPlayerLayout, type ChatHeaderVariant, type MiniPlayerLayout, type ShellRegion, type SpotifyImmersiveLayout } from './layout.js';
import { filterModelChoices, formatModelPanelLabel, modelPanelLabelWidth } from './model-selection.js';
import { buildPlaybackStatusIconLine } from './mini-progress-writer.js';
import { PANEL_BACKGROUND, PANEL_PRIMARY, PANEL_SECONDARY, PanelChoiceList, PanelEmptyRow, PanelFrame, PanelRow, resolvePanelChoiceSegments, type PanelChoiceItem } from './panel-frame.js';
import { SONEX_LOGO } from './sonex-logo.js';
import { formatTrackPanelLine, trackPanelTrackKey } from './track-panel.js';
import { withTrueColorBackground } from './terminal-frame-writer.js';
import { ExtensionPanelOverlay } from './extension-panel.js';
import type { CommittedTranscriptRecord } from './transcript.js';
import type { ActivityItem, ActivityKind, AuthMethodChoice, AuthRuntimeState, AuthSetupState, ChatBubbleProps, ChatMessageItem, ConfirmChoice, ConfirmState, ExtensionPanelState, HelpPanelState, LanguagePanelState, LoginScreenProps, MemoryPanelState, NetEaseLoginState, NetEaseQrItem, PlayerPaneVariant, PlayerState, PromptInputProps, ProviderModeState, SlashCommandSuggestion, SpotifyModeState, SpotifySetupState, TrackPanelState, TrackPanelTrack, TrackSummary, UiLanguage } from './types.js';

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

export const SonexLogo = () => {
    const useColor = process.env.NO_COLOR === undefined;
    return (
        <Box width="100%" flexDirection="column">
            {SONEX_LOGO.map((line, rowIndex) => (
                <Text
                    key={rowIndex}
                    color={useColor ? BORDER_BLUE_SOFT : undefined}
                    wrap="truncate-end"
                >
                    {line}
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

const WORKING_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"] as const;
const WORKING_SPINNER_INTERVAL_MS = 100;

export const AgentWorkingStatus = () => {
    const [frame, setFrame] = React.useState(0);

    React.useEffect(() => {
        const timer = setInterval(
            () => setFrame((current) => (current + 1) % WORKING_SPINNER_FRAMES.length),
            WORKING_SPINNER_INTERVAL_MS,
        );
        return () => clearInterval(timer);
    }, []);

    return (
        <Box height={1} flexShrink={0} paddingLeft={1} paddingRight={1} alignItems="flex-start">
            <Text color={CHAT_SYSTEM_MARKER_COLOR}>{WORKING_SPINNER_FRAMES[frame]} </Text>
            <Text color={CHAT_SYSTEM_MARKER_COLOR} italic>Working</Text>
            <Text color="#808791" bold> • Esc to interrupt</Text>
        </Box>
    );
};

export const formatAuthLabel = (state: AuthRuntimeState): string => {
    if (state.credential_source === "local" || state.auth_type === "local") {
        return "local";
    }
    if (!state.ready) {
        return "sign-in required";
    }
    if (state.auth_type === "api_key") {
        return "API billing";
    }
    if (state.auth_type === "oauth") {
        return "OAuth";
    }
    return state.auth_type || state.credential_source || "auth";
};

export const HeaderFrame = ({ authState, cwd, sessionId, variant, language = "en" }: {
    authState: AuthRuntimeState;
    cwd: string;
    sessionId: string | null;
    variant: ChatHeaderVariant;
    language?: UiLanguage;
}) => {
    const identityModel = authState.model_label || authState.model || authState.provider || FALLBACK_MODEL_NAME;
    const displayCwd = formatWorkingDirectory(cwd);
    const runtimeInformation = (
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
            <Text wrap="truncate-end"><Text bold color="#fff4f6">Sonex CLI</Text> <Text bold color={BORDER_BLUE}>v{APP_VERSION}</Text></Text>
            <Box height={1} />
            <Text color="#d8bcc7" wrap="truncate-end">
                {identityModel} • {authState.ready
                    ? formatAuthLabel(authState)
                    : <Text color="#facc15" bold>Not logged in</Text>}
            </Text>
            <Text color="#fff4f6" wrap="truncate-end">{displayCwd}</Text>
            {sessionId ? (
                <>
                    <Text color="#808791">session id:</Text>
                    <Text color="#fff4f6" wrap="truncate-end">{sessionId}</Text>
                </>
            ) : null}
        </Box>
    );
    if (variant === 'compact') {
        return (
            <Box width="100%" flexDirection="column" marginBottom={2}>
                {runtimeInformation}
            </Box>
        );
    }

    return (
        <Box width="100%" marginBottom={2}>
            <Mascot />
            {runtimeInformation}
        </Box>
    );
};

export const isGenericAuthSetup = (setup: AuthSetupState): boolean => {
    return Boolean(setup?.active);
};

const LoginChoiceList = ({ choices, selectedIndex, visibleLimit, showConnectionStatus = false }: {
    choices: AuthMethodChoice[];
    selectedIndex: number;
    visibleLimit?: number;
    showConnectionStatus?: boolean;
}) => {
    return (
        <PanelChoiceList
            items={choices.map((choice) => {
                const detail = choice.description
                    ? [{ text: `  ${choice.description}`, color: PANEL_SECONDARY }]
                    : [];
                const connectionStatus = choice.connection_status ?? (choice.connected ? "active" : "missing");
                const connectionColor = connectionStatus === "active"
                    ? SPOTIFY_GREEN
                    : connectionStatus === "missing"
                        ? "#ef4444"
                        : PANEL_SECONDARY;
                return {
                    key: choice.value,
                    segments: showConnectionStatus
                        ? [
                            {
                                text: "• ",
                                color: connectionColor,
                                preserveColorWhenSelected: true,
                            },
                            { text: choice.label, color: PANEL_PRIMARY },
                        ]
                        : [{ text: choice.label, color: PANEL_PRIMARY }, ...detail],
                };
            })}
            selectedIndex={selectedIndex}
            visibleLimit={visibleLimit}
            width={74}
            paddingX={2}
        />
    );
};

export const MAX_VISIBLE_LOGIN_PROVIDERS = 8;

export const NetEaseQrMessage = ({ item }: { item: NetEaseQrItem }) => {
    return (
        <Box flexDirection="row">
            <Text color={CHAT_SYSTEM_MARKER_COLOR}>• </Text>
            <Box flexDirection="column">
                <Text bold color={BORDER_BLUE}>{item.title}</Text>
                <Text>{item.output}</Text>
                <Text color="#808791">
                    {item.fallbackOnline ? "Esc to play online" : "Esc to cancel"}
                </Text>
            </Box>
        </Box>
    );
};

export const LoginScreen = ({
    authSetup,
    selectedIndex,
    apiKeyInput,
    setApiKeyInput,
    onApiKeySubmit,
    inputFocus = true,
    language = "en",
}: LoginScreenProps & { inputFocus?: boolean; language?: UiLanguage }) => {
    if (!authSetup) return null;

    const providerChoices = authSetup.providers ?? [];
    const methodChoices = authSetup.methods ?? [];
    const isProviderStep = authSetup.step === "provider";
    const isMethodStep = authSetup.step === "method";
    const modelChoices = authSetup.models ?? [];
    const isApiKeyStep = authSetup.step === "api_key";
    const isModelStep = authSetup.step === "model";
    const isOauthWait = authSetup.step === "oauth_wait";
    const isTextStep = !isProviderStep && !isMethodStep && !isModelStep && !isOauthWait;
    const choices = isProviderStep ? providerChoices : isMethodStep ? methodChoices : isModelStep ? modelChoices : [];
    const showProviderConnectionStatus = isProviderStep
        && providerChoices.length > 0
        && providerChoices.every((choice) => Boolean(choice.connection_status) || typeof choice.connected === "boolean");
    const displayMessage = isProviderStep
        ? t(language, "login.warmup")
        : authSetup.message;
    const helpRows = authSetup.help_text
        ? wrapChatMessageContent(authSetup.help_text, 70)
        : [];

    return (
        <PanelFrame width={74} paddingX={2} title={authSetup.title} hint={displayMessage}>
            {(isProviderStep || isMethodStep || isModelStep) ? (
                <>
                    <LoginChoiceList
                        choices={choices}
                        selectedIndex={selectedIndex}
                        visibleLimit={isProviderStep ? MAX_VISIBLE_LOGIN_PROVIDERS : isModelStep ? MAX_VISIBLE_MODEL_CHOICES : undefined}
                        showConnectionStatus={showProviderConnectionStatus}
                    />
                    <PanelRow
                        width={74}
                        paddingX={2}
                        segments={[{ text: t(language, "login.continue"), color: PANEL_SECONDARY, bold: true }]}
                    />
                </>
            ) : null}

            {isTextStep ? (
                <>
                    <PanelRow
                        width={74}
                        paddingX={2}
                        segments={[{ text: authSetup.prompt ?? "Value", color: PANEL_SECONDARY }]}
                    />
                    <PromptInput
                        input={apiKeyInput}
                        setInput={setApiKeyInput}
                        onSubmit={onApiKeySubmit}
                        focus={inputFocus}
                        placeholder={authSetup.placeholder ?? authSetup.prompt ?? "Value"}
                        mask={authSetup.mask || isApiKeyStep ? "*" : undefined}
                        backgroundColor={PANEL_BACKGROUND}
                        backgroundWidth={74}
                        backgroundPaddingX={2}
                    />
                    {helpRows.map((row, index) => (
                        <PanelRow
                            key={`auth-help-${index}`}
                            width={74}
                            paddingX={2}
                            segments={[{ text: row, color: PANEL_SECONDARY, italic: true }]}
                        />
                    ))}
                </>
            ) : null}

            {isOauthWait ? (
                <>
                    <PanelRow
                        width={74}
                        paddingX={2}
                        segments={[{ text: t(language, "auth.oauth.waiting"), color: BORDER_BLUE_SOFT }]}
                    />
                    <PanelRow
                        width={74}
                        paddingX={2}
                        segments={[{ text: t(language, "auth.oauth.return"), color: PANEL_SECONDARY }]}
                    />
                </>
            ) : null}
        </PanelFrame>
    );
};

const fillPromptInputBackground = (
    output: string,
    backgroundWidth?: number,
    backgroundPaddingX = 0,
): string => {
    if (!backgroundWidth) return output;
    const width = Math.max(1, Math.floor(backgroundWidth));
    const paddingX = Math.max(0, Math.min(Math.floor(backgroundPaddingX), Math.floor(width / 2)));
    return output.split("\n").map((line) => (
        `${" ".repeat(paddingX)}${line}${" ".repeat(Math.max(
            paddingX,
            width - paddingX - stringWidth(line),
        ))}`
    )).join("\n");
};

const PromptInput = ({
    input,
    setInput,
    onSubmit,
    focus,
    placeholder,
    mask,
    inputRevision,
    backgroundColor,
    backgroundWidth,
    backgroundPaddingX = 0,
}: PromptInputProps) => {
    const [cursorVisible, setCursorVisible] = React.useState(true);

    React.useEffect(() => {
        setCursorVisible(true);
        if (!focus) return;

        const timer = setInterval(() => setCursorVisible((visible) => !visible), INPUT_CURSOR_BLINK_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [focus, input, inputRevision]);

    return (
        <Text>
            <Transform transform={(output) => {
                const visibleOutput = focus && cursorVisible ? output : hideInputCursor(output);
                const filledOutput = fillPromptInputBackground(
                    visibleOutput,
                    backgroundWidth,
                    backgroundPaddingX,
                );
                return backgroundColor
                    ? withTrueColorBackground(filledOutput, backgroundColor)
                    : filledOutput;
            }}>
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
        </Text>
    );
};

type ConfirmChoiceLabel = {
    key: string;
    label: string;
    description?: string | null;
    display?: ConfirmChoice["display"];
    labelWidth?: number;
};

const COMMAND_LIST_LABEL_WIDTH = 12;
const CONFIRM_CHOICE_LABEL_WIDTH = 18;
const CONFIRM_CHOICE_ROW_LABEL_WIDTH = 102;
const PLAYLIST_BROWSE_NAME_WIDTH = 32;
const MEMORY_SETTING_LABEL_WIDTH = 48;
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

const formatMemorySettingRow = (label: string, value: string): string => (
    `${fitDisplayWidth(label, MEMORY_SETTING_LABEL_WIDTH)}${value}`
);

const formatCommandListLabel = (command: Pick<SlashCommandSuggestion, "name">): string => (
    `/${command.name}`.slice(0, COMMAND_LIST_LABEL_WIDTH).padEnd(COMMAND_LIST_LABEL_WIDTH, " ")
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

const formatConfirmChoiceLabel = (row: ConfirmChoiceLabel): string => (
    row.display?.kind === "music_candidate"
        ? formatMusicCandidateDisplayLabel(row.display, CONFIRM_CHOICE_ROW_LABEL_WIDTH, row.description)
        : row.labelWidth
        ? row.label + " ".repeat(Math.max(0, row.labelWidth - stringWidth(row.label)))
        : row.label
);

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

const HelpPanel = ({ panel, selectedIndex, width, language = "en" }: {
    panel: HelpPanelState;
    selectedIndex: number;
    width: number;
    language?: UiLanguage;
}) => {
    if (!panel) return null;
    const commands = helpPanelCommands(panel.commands);
    const items: PanelChoiceItem[] = commands.map((command) => ({
        key: command.name,
        segments: [
            { text: formatCommandListLabel(command), color: PANEL_PRIMARY },
            { text: command.description, color: PANEL_SECONDARY },
        ],
    }));

    return (
        <PanelFrame width={width} title={panel.title} hint={panel.hint}>
            {panel.commands.length === 0 ? (
                <PanelRow
                    width={width}
                    segments={[{ text: t(language, "help.empty"), color: PANEL_SECONDARY }]}
                />
            ) : (
                <PanelChoiceList
                    items={items}
                    selectedIndex={selectedIndex}
                    visibleLimit={HELP_PANEL_VISIBLE_COMMANDS}
                    width={width}
                />
            )}
        </PanelFrame>
    );
};

export const ChatBubble = ({ role, content, contentWidth, theme = null, tone = null, segments = null, document = null, showDivider = true }: ChatBubbleProps) => {
    const isUser = role === "user";
    const markerColor = resolveChatMarkerColor(role, theme, tone);
    const contentColor = resolveChatContentColor(role, tone);
    const semanticTheme = resolveAgentChatTheme(theme);
    const useToolSegmentStyles = !isUser && tone === null;
    const semanticSegments = !isUser && tone === null && document?.version === 1
        ? chatDocumentSegments(document)
        : null;
    const candidateSegments = semanticSegments ?? segments;
    const validSegments = candidateSegments && candidateSegments.map((segment) => segment.text).join("") === content
        ? candidateSegments
        : null;
    const richLines = validSegments ? wrapChatMessageSegments(validSegments, contentWidth) : null;
    const lines = richLines ?? wrapChatMessageContent(content, contentWidth);

    return (
        <Box marginBottom={1} flexDirection="column" width="100%">
            {lines.map((line, index) => {
                const marker = index === 0 ? "•" : " ";
                if (typeof line === "string") {
                    return (
                        <Text key={`${index}_${line}`}>
                            <Text bold color={markerColor}>{marker}</Text>
                            <Text color={contentColor}>{` ${line}`}</Text>
                        </Text>
                    );
                }
                return (
                    <Text key={`${index}_${line.map((segment) => segment.text).join("")}`}>
                        <Text bold color={markerColor}>{marker}</Text>
                        <Text color={contentColor}>{" "}</Text>
                        {line.map((segment, segmentIndex) => (
                            <Text
                                key={`${segmentIndex}_${segment.text}`}
                                color={
                                    useToolSegmentStyles && segment.style === "tool_name"
                                        ? TOOL_NAVY
                                        : segment.style === "heading" || segment.style === "strong" || segment.style === "list_marker"
                                            ? semanticTheme.strongText
                                            : segment.style === "link"
                                                ? semanticTheme.linkText
                                                : contentColor
                                }
                                backgroundColor={
                                    segment.style === "highlight"
                                        ? semanticTheme.highlightBackground
                                        : segment.style === "code"
                                            ? semanticTheme.codeBackground
                                            : undefined
                                }
                                bold={
                                    (useToolSegmentStyles && segment.style === "tool_name")
                                    || ["heading", "strong", "highlight", "list_marker"].includes(segment.style)
                                }
                                underline={segment.style === "link"}
                            >
                                {segment.text}
                            </Text>
                        ))}
                    </Text>
                );
            })}
            {showDivider ? (
                <Box marginTop={1}>
                    <Text color={CHAT_USER_MARKER_COLOR}>{"─".repeat(contentWidth + 2)}</Text>
                </Box>
            ) : null}
        </Box>
    );
};

export const CommittedRecord = ({
    record,
}: {
    record: CommittedTranscriptRecord;
}) => (
    <Box flexDirection="column" paddingX={1}>
        {record.item.type === "info_banner" ? (
            <>
                {record.item.showLogo ? (
                    <>
                        <SonexLogo />
                        <Box height={1} />
                    </>
                ) : null}
                <HeaderFrame
                    authState={record.item.authState}
                    cwd={record.item.cwd}
                    sessionId={record.item.sessionId}
                    variant={record.presentation.headerVariant}
                    language={record.presentation.language}
                />
            </>
        ) : record.item.type === "netease_qr" ? (
            <NetEaseQrMessage item={record.item} />
        ) : (
            <ChatBubble
                role={record.item.role}
                content={record.item.content}
                contentWidth={record.presentation.contentWidth}
                theme={record.item.theme}
                tone={record.item.tone}
                segments={record.item.segments}
                document={record.item.document}
            />
        )}
    </Box>
);

export const CommittedTranscript = ({
    records,
}: {
    records: CommittedTranscriptRecord[];
}) => (
    <Static items={records}>
        {(record) => (
            <CommittedRecord
                key={record.sequence}
                record={record}
            />
        )}
    </Static>
);

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

const TrackPanel = ({
    panel,
    panelWidth,
    expanded = false,
    selectedIndex = 0,
    spotifyTheme = false,
    language = "en",
}: {
    panel: TrackPanelState;
    panelWidth: number;
    expanded?: boolean;
    selectedIndex?: number;
    spotifyTheme?: boolean;
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
    const titleRows = 1;
    const hintRows = panel.hint ? 1 : 0;
    const paddingRows = 1;
    const availableRows = Math.max(
        TRACK_PANEL_MIN_VISIBLE_ROWS,
        panelHeight > 0 ? panelHeight - titleRows - hintRows - paddingRows - 2 : TRACK_PANEL_MIN_VISIBLE_ROWS,
    );

    const visibleRowCount = panel.tracks.length === 0
        ? 1
        : Math.min(panel.tracks.length, availableRows);
    const fillerRowCount = Math.max(0, availableRows - visibleRowCount);
    const items: PanelChoiceItem[] = panel.tracks.map((track) => ({
        key: `${track.index}-${trackPanelTrackKey(track)}`,
        segments: [{
            text: formatTrackPanelLine(track, TRACK_PANEL_ROW_WIDTH),
            color: PANEL_PRIMARY,
        }],
    }));

    return (
        <Box
            ref={panelRef}
            flexDirection="column"
            flexGrow={expanded ? 1 : 0}
            flexShrink={0}
            minHeight={0}
            height={expanded ? "100%" : undefined}
        >
            <PanelFrame
                width={panelWidth}
                paddingX={2}
                title={panelTitle}
                hint={panel.hint ? `${panel.hint}; Esc to hide` : null}
            >
                {panel.tracks.length === 0 ? (
                    <PanelRow
                        width={panelWidth}
                        paddingX={2}
                        segments={[{ text: trackPanelEmptyText(panel, language), color: PANEL_SECONDARY }]}
                    />
                ) : (
                    <PanelChoiceList
                        items={items}
                        selectedIndex={selectedIndex}
                        visibleLimit={availableRows}
                        width={panelWidth}
                        paddingX={2}
                        spotifyTheme={spotifyTheme}
                    />
                )}
                {Array.from({ length: fillerRowCount }, (_unused, index) => (
                    <PanelEmptyRow key={`track-panel-filler-${index}`} width={panelWidth} />
                ))}
            </PanelFrame>
        </Box>
    );
};

const TrackPanelOverlay = ({
    trackPanel,
    selectedIndex = 0,
    panelWidth,
    spotifyTheme = false,
    language = "en",
}: {
    trackPanel: TrackPanelState;
    selectedIndex?: number;
    panelWidth: number;
    spotifyTheme?: boolean;
    language?: UiLanguage;
}) => (
    <Box width="100%" height="100%" flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
        <TrackPanel
            panel={trackPanel}
            panelWidth={panelWidth}
            expanded={true}
            selectedIndex={selectedIndex}
            spotifyTheme={spotifyTheme}
            language={language}
        />
    </Box>
);

const MemoryPanelOverlay = ({ panel, selectedIndex = 0, searchQuery = "", editor = null, panelWidth = 74 }: {
    panel: MemoryPanelState;
    selectedIndex?: number;
    searchQuery?: string;
    editor?: { mode: "search" | "add" | "edit" | "setting"; value: string; settingKey?: string } | null;
    panelWidth?: number;
}) => {
    if (!panel) return null;
    const width = Math.max(3, Math.min(74, Math.floor(panelWidth)));
    if (editor) {
        return (
            <Box width="100%" flexDirection="column" flexShrink={0} paddingX={1}>
                <PanelFrame
                    width={width}
                    paddingX={2}
                    title={editor.mode === "search"
                        ? "Search memory"
                        : editor.mode === "add"
                            ? "Add memory"
                            : editor.mode === "edit"
                                ? "Edit memory"
                                : "Change memory setting"}
                    hint={editor.mode === "search" || editor.mode === "setting"
                        ? "Enter to apply; Esc to cancel"
                        : "Ctrl+S to save; Enter for a new line; Esc to cancel"}
                >
                    <PanelRow
                        width={width}
                        paddingX={2}
                        segments={[{ text: `${editor.mode === "search" ? "/" : ""}${editor.value || " "}`, color: PANEL_PRIMARY }]}
                    />
                </PanelFrame>
            </Box>
        );
    }
    const rootItems = panel.view === "root"
        ? ["view memory entries", "reset memory"]
        : panel.view === "sources"
            ? ["USER.md", "MEMORY.md", "Memory Dump"]
            : panel.view === "format"
                ? ["USER.md", "MEMORY.md", "All memory"]
            : panel.view === "settings"
                ? [
                    formatMemorySettingRow("Forget retention", `${panel.settings?.forget_retention_days ?? 7} days`),
                    formatMemorySettingRow("USER.md capacity", String(panel.settings?.user_capacity ?? "Unlimited")),
                    formatMemorySettingRow("MEMORY.md capacity", String(panel.settings?.memory_capacity ?? "Unlimited")),
                    formatMemorySettingRow("Automatic forgetting", String(panel.settings?.automatic_forgetting ?? "off")),
                    formatMemorySettingRow("Idle threshold", `${panel.settings?.idle_threshold_days ?? 30} days`),
                    formatMemorySettingRow("Automatic refinement", panel.settings?.automatic_refinement === false ? "Off" : "On"),
                    formatMemorySettingRow("USER.md refinement window", String(panel.settings?.user_refinement_window ?? 8)),
                    formatMemorySettingRow("MEMORY.md refinement window", String(panel.settings?.memory_refinement_window ?? 12)),
                ]
                : [];
    if (panel.view === "detail") {
        const entry = panel.entries[0];
        const revisions = Array.isArray(panel.settings?.revisions) ? panel.settings.revisions : [];
        return (
            <Box width="100%" flexDirection="column" flexShrink={0} paddingX={1}>
                <PanelFrame width={width} paddingX={2} title={`${panel.title}${panel.readOnly ? " · Read only" : ""}`} hint={panel.hint}>
                    {entry ? (
                        <Box flexDirection="column" paddingX={2}>
                            <Text color={PANEL_PRIMARY}>{entry.content}</Text>
                            <Text color={PANEL_SECONDARY}>{entry.protected ? "Protected" : "Inferred"} · {entry.source}</Text>
                            <Text color={PANEL_SECONDARY}>Updated: {entry.updated_at ?? "Never"}</Text>
                            <Text color={PANEL_SECONDARY}>Recalled: {entry.recall_count ?? 0} · Last: {entry.last_recalled_at ?? "Never"}</Text>
                            {entry.reason ? <Text color={PANEL_SECONDARY}>Reason: {entry.reason}</Text> : null}
                            {entry.expires_at ? <Text color={PANEL_SECONDARY}>Expires: {entry.expires_at}</Text> : null}
                            {entry.review_pending ? <Text color="#facc15" bold>Review pending</Text> : null}
                            <Text color={PANEL_SECONDARY}>Revisions: {revisions.length}</Text>
                        </Box>
                    ) : <PanelRow width={width} paddingX={2} segments={[{ text: "Memory entry is unavailable.", color: PANEL_SECONDARY }]} />}
                </PanelFrame>
            </Box>
        );
    }
    const items: PanelChoiceItem[] = rootItems.length > 0
        ? rootItems.map((label) => ({ key: label, segments: [{ text: label, color: PANEL_PRIMARY }] }))
        : panel.entries
        .filter((entry) => entry.content.toLocaleLowerCase().includes(searchQuery.toLocaleLowerCase()))
        .map((entry) => ({
            key: entry.entry_id,
            segments: [{
                text: panel.view === "revisions"
                    ? `${entry.content.replaceAll("\n", " ").slice(0, 56)}  ${entry.source ?? "unknown"}`
                    : `${entry.content.replaceAll("\n", " ").slice(0, 64)}  ${entry.protected ? "Protected" : "Inferred"}${entry.review_pending ? " · Review pending" : ""}`,
                color: PANEL_PRIMARY,
            }],
        }));
    return (
        <Box width="100%" flexDirection="column" flexShrink={0} paddingX={1}>
            <PanelFrame
                width={width}
                paddingX={2}
                title={`${panel.title}${panel.readOnly ? " · Read only" : ""}`}
                hint={searchQuery ? `Filter: /${searchQuery} · ${panel.hint ?? ""}` : panel.hint}
            >
                {items.length > 0 ? (
                    <PanelChoiceList
                        items={items}
                        selectedIndex={selectedIndex}
                        visibleLimit={12}
                        width={width}
                        paddingX={2}
                    />
                ) : (
                    <PanelRow
                        width={width}
                        paddingX={2}
                        segments={[{ text: "No memory entries.", color: PANEL_SECONDARY }]}
                    />
                )}
            </PanelFrame>
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
    const statusLine = buildPlaybackStatusIconLine(player, infoInnerWidth, Date.now());

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
                    <Text bold color={visual.accent}>Now playing</Text>
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
    choices.some((choice) => choice.value === "deny" || choice.value === "cancel")
        ? "press Esc to cancel"
        : "press Esc to close"
);

export const CompactConfirm = ({
    confirm,
    confirmIndex,
    input,
    setInput,
    onSubmit,
    inputFocus,
    inputRevision,
    panelWidth,
    spotifyTheme = false,
}: {
    confirm: ConfirmState;
    confirmIndex: number;
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    inputFocus: boolean;
    inputRevision: number;
    panelWidth: number;
    spotifyTheme?: boolean;
}) => {
    if (!confirm) return null;
    const includeCancelChoice = confirm.tool_name === "provider_mode_exit";
    const visibleChoices = getVisibleConfirmChoices(confirm.choices, includeCancelChoice);
    const selectedDisplayIndex = resolveConfirmChoiceDisplayIndex(confirm.choices, confirmIndex, includeCancelChoice);
    const isSpotifyConfirm = spotifyTheme || confirm.tool_name === "spotify_device";
    const isSongCandidateConfirm = confirm.tool_name === "song_candidate";

    if (confirm.variant === "tool_call_review") {
        const contentWidth = Math.max(1, panelWidth - 2);
        return (
            <PanelFrame
                width={panelWidth}
                title={confirm.message}
                hint={confirm.warning ?? "Please review the Bash command(s) below before permission."}
                hintColor="#facc15"
            >
                {(confirm.commands ?? []).map((command, commandIndex) => (
                    <React.Fragment key={`${commandIndex}-${command}`}>
                        {commandIndex > 0 ? <PanelEmptyRow width={panelWidth} /> : null}
                        {wrapChatMessageContent(command, contentWidth).map((row, rowIndex) => (
                            <PanelRow
                                key={`${commandIndex}-${rowIndex}-${row}`}
                                width={panelWidth}
                                segments={[{ text: row, color: TOOL_VALUE }]}
                            />
                        ))}
                    </React.Fragment>
                ))}
                <PanelEmptyRow width={panelWidth} />
                <PanelChoiceList
                    items={visibleChoices.map((choice) => ({
                        key: choice.value,
                        segments: [{ text: choice.label, color: PANEL_PRIMARY }],
                    }))}
                    selectedIndex={selectedDisplayIndex}
                    width={panelWidth}
                />
            </PanelFrame>
        );
    }

    if (isSongCandidateConfirm) {
        const contentWidth = Math.max(1, panelWidth - 2);
        const boundedIndex = selectedDisplayIndex;

        return (
            <PanelFrame width={panelWidth} title={confirm.message} hint="press Esc to cancel">
                {visibleChoices.map((choice, index) => {
                    const selected = index === boundedIndex;
                    const isSupplementChoice = Boolean(choice.input);
                    const label = formatConfirmChoiceLabel({
                        key: choice.value,
                        label: choice.label,
                        description: choice.description,
                        display: choice.display,
                        labelWidth: CONFIRM_CHOICE_LABEL_WIDTH,
                    });
                    const visibleLabel = truncateDisplayWidth(label, contentWidth);
                    const item: PanelChoiceItem = {
                        key: choice.value,
                        segments: [{
                            text: visibleLabel,
                            color: isSupplementChoice ? PANEL_SECONDARY : PANEL_PRIMARY,
                        }],
                        unselectedBold: isSupplementChoice,
                    };
                    return (
                        <React.Fragment key={choice.value}>
                            {isSupplementChoice ? (
                                <PanelEmptyRow width={panelWidth} />
                            ) : null}
                            {isSupplementChoice && selected ? (
                                <PromptInput
                                    input={input}
                                    setInput={setInput}
                                    onSubmit={onSubmit}
                                    focus={selected && inputFocus}
                                    placeholder=""
                                    inputRevision={inputRevision}
                                    backgroundColor={PANEL_BACKGROUND}
                                    backgroundWidth={panelWidth}
                                    backgroundPaddingX={1}
                                />
                            ) : (
                                <PanelRow
                                    width={panelWidth}
                                    segments={resolvePanelChoiceSegments(item, selected, false)}
                                />
                            )}
                        </React.Fragment>
                    );
                })}
            </PanelFrame>
        );
    }

    const choiceItems: PanelChoiceItem[] = visibleChoices.map((choice) => ({
        key: choice.value,
        segments: choice.display?.kind === "music_candidate"
            ? [{ text: formatMusicCandidateDisplayLabel(choice.display, CONFIRM_CHOICE_ROW_LABEL_WIDTH, choice.description), color: PANEL_PRIMARY }]
            : [
                {
                    text: choice.label + " ".repeat(Math.max(0, CONFIRM_CHOICE_LABEL_WIDTH - stringWidth(choice.label))),
                    color: choice.disabled ? PANEL_SECONDARY : PANEL_PRIMARY,
                },
                ...((choice.disabled_reason ?? choice.description)
                    ? [{ text: choice.disabled_reason ?? choice.description ?? "", color: PANEL_SECONDARY }]
                    : []),
            ],
    }));

    if (confirm.tool_name === "playlist_browse") {
        const playlistItems: PanelChoiceItem[] = visibleChoices.map((choice) => ({
            key: choice.value,
            segments: [
                { text: formatPlaylistBrowseName(choice.label), color: PANEL_PRIMARY },
                { text: ` ${playlistBrowseTrackCount(choice)}`, color: PANEL_SECONDARY },
            ],
        }));
        return (
            <PanelFrame width={panelWidth} title={confirm.message} hint={confirmCancelHint(confirm.choices)}>
                <PanelChoiceList
                    items={playlistItems}
                    selectedIndex={selectedDisplayIndex}
                    width={panelWidth}
                    spotifyTheme={isSpotifyConfirm}
                />
            </PanelFrame>
        );
    }

    if (confirm.tool_name === "provider_mode_exit") {
        return (
            <PanelFrame
                width={panelWidth}
                title={confirm.message}
                hint={null}
                titleDetailSegments={confirm.warning ? [
                    { text: "Warning: ", color: "#facc15", bold: true },
                    { text: confirm.warning, color: "#facc15", italic: true },
                ] : null}
            >
                <PanelChoiceList
                    items={choiceItems}
                    selectedIndex={selectedDisplayIndex}
                    width={panelWidth}
                    spotifyTheme={isSpotifyConfirm}
                />
            </PanelFrame>
        );
    }

    return (
        <PanelFrame
            width={panelWidth}
            title={confirm.message}
            hint={confirm.hide_hint ? null : confirmCancelHint(confirm.choices)}
        >
            <PanelChoiceList
                items={choiceItems}
                selectedIndex={selectedDisplayIndex}
                width={panelWidth}
                spotifyTheme={isSpotifyConfirm}
            />
        </PanelFrame>
    );
};

const LanguagePanel = ({ panel, selectedIndex, width, language = "en" }: {
    panel: LanguagePanelState;
    selectedIndex: number;
    width: number;
    language?: UiLanguage;
}) => {
    if (!panel) return null;
    const choices = orderedLanguageChoices(panel.selected);
    const boundedIndex = Math.min(Math.max(selectedIndex, 0), choices.length - 1);
    return (
        <PanelFrame width={width} title={t(language, "language.title")} hint={t(language, "language.hint")}>
            <PanelChoiceList
                items={choices.map((choice) => ({
                    key: choice,
                    segments: [{
                        text: choice === panel.selected ? `* ${languageLabel(choice)}` : languageLabel(choice),
                        color: PANEL_PRIMARY,
                    }],
                }))}
                selectedIndex={boundedIndex}
                width={width}
            />
            {panel.saveError ? (
                <PanelRow width={width} segments={[{ text: panel.saveError, color: "#ff9c9c" }]} />
            ) : null}
        </PanelFrame>
    );
};

type CompactSetupPanel = NonNullable<SpotifySetupState | AuthSetupState>;

const setupDoneHint = (setupPanel: CompactSetupPanel, _language: UiLanguage): string | null => {
    if (setupPanel.active) return null;
    return "press Esc to hide";
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
    terminalColumns,
    language = "en",
}: {
    setupPanel: CompactSetupPanel | null;
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    inputPlaceholder: string;
    inputMask?: string;
    inputFocus: boolean;
    inputRevision: number;
    terminalColumns: number | null;
    language?: UiLanguage;
}) => {
    if (!setupPanel) return null;

    const panelWidth = Math.max(3, Math.floor(terminalColumns ?? 80));
    const contentWidth = Math.max(1, panelWidth - 2);
    const messageRows = wrapChatMessageContent(setupPanel.message, contentWidth);

    return (
        <PanelFrame
            width={panelWidth}
            title={setupPanel.title}
        >
            {messageRows.map((row, index) => (
                <PanelRow
                    key={`setup-message-${index}`}
                    width={panelWidth}
                    segments={[{
                        text: row,
                        color: setupMessageColor(setupPanel),
                    }]}
                />
            ))}
            {setupDoneHint(setupPanel, language) ? (
                <PanelRow
                    width={panelWidth}
                    segments={[{ text: setupDoneHint(setupPanel, language) ?? "", color: PANEL_SECONDARY }]}
                />
            ) : null}
            {"provider" in setupPanel && setupPanel.providers && setupPanel.providers.length > 0 ? (
                <PanelRow
                    width={panelWidth}
                    segments={[{
                        text: `${t(language, "providers.label")}: ${setupPanel.providers.map((provider) => provider.value).join(" / ")}`,
                        color: PANEL_SECONDARY,
                    }]}
                />
            ) : null}
            {"provider" in setupPanel && setupPanel.methods && setupPanel.methods.length > 0 ? (
                <PanelRow
                    width={panelWidth}
                    segments={[{
                        text: `${t(language, "methods.label")}: ${setupPanel.methods.map((method) => method.value).join(" / ")}`,
                        color: PANEL_SECONDARY,
                    }]}
                />
            ) : null}
            {setupPanel.active && setupPanel.prompt ? (
                <PromptInput
                    input={input}
                    setInput={setInput}
                    onSubmit={onSubmit}
                    focus={inputFocus}
                    placeholder={setupPanel.prompt ?? inputPlaceholder}
                    mask={setupPanel.mask ? "*" : inputMask}
                    inputRevision={inputRevision}
                    backgroundColor={PANEL_BACKGROUND}
                    backgroundWidth={panelWidth}
                    backgroundPaddingX={1}
                />
            ) : null}
        </PanelFrame>
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
    providerMode,
    spotifySetup,
    authSetup,
    modelStatus,
    slashSuggestions,
    slashIndex,
    helpPanel,
    helpPanelIndex,
    languagePanel,
    languagePanelIndex,
    modelPanelIndex,
    terminalColumns,
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
    providerMode: ProviderModeState;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
    modelStatus: string | null;
    slashSuggestions: SlashCommandSuggestion[];
    slashIndex: number;
    helpPanel: HelpPanelState;
    helpPanelIndex: number;
    languagePanel: LanguagePanelState;
    languagePanelIndex: number;
    modelPanelIndex: number;
    terminalColumns: number | null;
    minimal?: boolean;
    switchHint?: string | null;
    language?: UiLanguage;
}) => {
    const selectedChoice = confirm?.choices[Math.min(confirmIndex, Math.max(0, confirm.choices.length - 1))] ?? null;
    const setupPanel = spotifySetup ?? (authSetup && authSetup.step !== "model" ? authSetup : null);
    const spotifyTheme = Boolean(spotifyMode?.enabled || spotifySetup);
    const isSongCandidateConfirm = confirm?.tool_name === "song_candidate";
    const insetPanelWidth = Math.max(3, Math.floor(terminalColumns ?? 80) - 2);
    const allModelChoices = authSetup?.models ?? [];
    const filteredModelChoices = filterModelChoices(allModelChoices, input);
    const modelLabelWidth = modelPanelLabelWidth(allModelChoices);
    const modelPanel = authSetup?.active && authSetup.step === "model"
        ? {
            title: authSetup.title,
            hint: authSetup.message,
            items: filteredModelChoices.map((model) => ({
                key: model.value,
                segments: [
                    { text: formatModelPanelLabel(model, modelLabelWidth), color: PANEL_PRIMARY },
                    { text: model.provider ?? model.value, color: PANEL_SECONDARY },
                ],
            })),
        }
        : null;
    const showInput = !setupPanel
        && !helpPanel
        && !languagePanel
        && !modelPanel
        && (!confirm || Boolean(selectedChoice?.input) && !isSongCandidateConfirm);
    const spotifyModeBorderLabel = " 🎧 Spotify Mode ";

    return (
        <Box flexDirection="column">
            {!minimal ? (
                <Box flexDirection="column" flexShrink={0} paddingX={1}>
                    <HelpPanel panel={helpPanel} selectedIndex={helpPanelIndex} width={insetPanelWidth} language={language} />
                    <SlashCommandList suggestions={slashSuggestions} selectedIndex={slashIndex} spotifyTheme={spotifyTheme} />
                    {!isSongCandidateConfirm ? (
                        <CompactConfirm
                            confirm={confirm}
                            confirmIndex={confirmIndex}
                            input={input}
                            setInput={setInput}
                            onSubmit={onSubmit}
                            inputFocus={inputFocus}
                            inputRevision={inputRevision}
                            panelWidth={insetPanelWidth}
                            spotifyTheme={spotifyTheme}
                        />
                    ) : null}
                    <LanguagePanel panel={languagePanel} selectedIndex={languagePanelIndex} width={insetPanelWidth} language={language} />
                    {modelPanel ? (
                        <PanelFrame width={insetPanelWidth} title={modelPanel.title} hint={modelPanel.hint}>
                            <PanelRow
                                width={insetPanelWidth}
                                segments={[
                                    { text: "Search: ", color: PANEL_SECONDARY },
                                    { text: input || "type to filter", color: input ? PANEL_PRIMARY : PANEL_SECONDARY },
                                ]}
                            />
                            <PanelChoiceList
                                items={modelPanel.items}
                                selectedIndex={modelPanelIndex}
                                visibleLimit={MAX_VISIBLE_MODEL_CHOICES}
                                width={insetPanelWidth}
                                spotifyTheme={spotifyTheme}
                            />
                            <PanelRow
                                width={insetPanelWidth}
                                segments={[{ text: t(language, "login.continue"), color: PANEL_SECONDARY, bold: true }]}
                            />
                        </PanelFrame>
                    ) : null}
                </Box>
            ) : null}
            {isSongCandidateConfirm || minimal ? (
                <CompactConfirm
                    confirm={confirm}
                    confirmIndex={confirmIndex}
                    input={input}
                    setInput={setInput}
                    onSubmit={onSubmit}
                    inputFocus={inputFocus}
                    inputRevision={inputRevision}
                    panelWidth={isSongCandidateConfirm
                        ? Math.max(3, Math.floor(terminalColumns ?? 80))
                        : insetPanelWidth}
                    spotifyTheme={spotifyTheme}
                />
            ) : null}
            {setupPanel ? <CompactSetup
                setupPanel={setupPanel}
                input={input}
                setInput={setInput}
                onSubmit={onSubmit}
                inputPlaceholder={inputPlaceholder}
                inputMask={inputMask}
                inputFocus={inputFocus}
                inputRevision={inputRevision}
                terminalColumns={terminalColumns}
                language={language}
            /> : null}
            {showInput ? (
                <>
                    <Box borderTop={true} borderBottom={true} borderLeft={false} borderRight={false}
                        borderStyle="single" borderColor="#808791"
                        paddingX={1} paddingTop={0} flexDirection="column"
                        minHeight={3} flexShrink={0}>
                        <Box flexDirection="row">
                            <Text color="#7f5d6b">
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
                    <Box height={1} paddingX={1} flexDirection="row">
                        <Box flexGrow={1} minWidth={0}>
                            {modelStatus ? (
                                <Text color="#808791" wrap="truncate-end">{modelStatus}</Text>
                            ) : null}
                        </Box>
                        <Box flexShrink={0}>
                            {spotifyMode?.enabled ? (
                                <Text bold color={SPOTIFY_GREEN}>{spotifyModeBorderLabel}</Text>
                            ) : null}
                        </Box>
                    </Box>
                </>
            ) : null}
        </Box>
    );
};

export const DynamicTail = ({
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
    providerMode,
    spotifySetup,
    authSetup,
    modelStatus,
    slashSuggestions,
    slashIndex,
    helpPanel,
    helpPanelIndex,
    languagePanel,
    languagePanelIndex,
    modelPanelIndex,
    memoryPanel,
    memoryPanelIndex,
    memorySearchQuery,
    memoryEditor,
    terminalColumns,
    agentWorking,
    streamingMessage,
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
    providerMode: ProviderModeState;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
    modelStatus: string | null;
    slashSuggestions: SlashCommandSuggestion[];
    slashIndex: number;
    helpPanel: HelpPanelState;
    helpPanelIndex: number;
    languagePanel: LanguagePanelState;
    languagePanelIndex: number;
    modelPanelIndex: number;
    memoryPanel: MemoryPanelState;
    memoryPanelIndex: number;
    memorySearchQuery: string;
    memoryEditor: { mode: "search" | "add" | "edit" | "setting"; value: string; settingKey?: string } | null;
    terminalColumns: number | null;
    agentWorking: boolean;
    streamingMessage: ChatMessageItem | null;
    language?: UiLanguage;
}) => {
    const selectedChoice = confirm?.choices[Math.min(confirmIndex, Math.max(0, confirm.choices.length - 1))] ?? null;
    const hasModelPanel = authSetup?.active && authSetup.step === "model";
    const hasSetupPanel = Boolean(spotifySetup) || Boolean(authSetup && authSetup.step !== "model");
    const hasSlashPanel = slashSuggestions.length > 0;
    const showInput = !helpPanel && !languagePanel && !hasModelPanel && !memoryPanel && (!confirm || Boolean(selectedChoice?.input));
    const showMiniMascotStatus = showInput && !confirm && !hasSlashPanel && !hasSetupPanel;

    return (
        <Box flexDirection="column">
            {streamingMessage ? (
                <Box flexDirection="column" paddingX={1}>
                    <ChatBubble
                        role={streamingMessage.role}
                        content={streamingMessage.content}
                        contentWidth={Math.max(1, (terminalColumns ?? 80) - 4)}
                        theme={streamingMessage.theme}
                        tone={streamingMessage.tone}
                        showDivider={false}
                    />
                </Box>
            ) : null}
            {showMiniMascotStatus ? (
                agentWorking ? <AgentWorkingStatus /> : <MiniMascotStatus />
            ) : null}
            {memoryPanel ? (
                <MemoryPanelOverlay
                    panel={memoryPanel}
                    selectedIndex={memoryPanelIndex}
                    searchQuery={memorySearchQuery}
                    editor={memoryEditor}
                    panelWidth={Math.max(3, Math.floor(terminalColumns ?? 80) - 2)}
                />
            ) : null}
            {!memoryPanel ? (
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
                    providerMode={providerMode}
                    spotifySetup={spotifySetup}
                    authSetup={authSetup}
                    modelStatus={modelStatus}
                    slashSuggestions={slashSuggestions}
                    slashIndex={slashIndex}
                    helpPanel={helpPanel}
                    helpPanelIndex={helpPanelIndex}
                    languagePanel={languagePanel}
                    languagePanelIndex={languagePanelIndex}
                    modelPanelIndex={modelPanelIndex}
                    terminalColumns={terminalColumns}
                    language={language}
                />
            ) : null}
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

const ProviderImmersiveRegion = ({
    player,
    spotifyMode,
    providerMode,
    spotifyImmersiveLayout,
}: {
    player: PlayerState;
    spotifyMode: SpotifyModeState;
    providerMode: ProviderModeState;
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
                    <Text color={SPOTIFY_GREEN} wrap="truncate-end">
                        {providerMode.connection_status === "disconnected" ? "reconnecting" : `${deviceStatus} on ${deviceName}`}
                    </Text>
                </Box>
            </Box>
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
    player,
    coverUrl,
    coverPattern,
    confirm,
    confirmIndex,
    spotifyMode,
    providerMode,
    spotifySetup,
    authSetup,
    modelStatus,
    slashSuggestions,
    slashIndex,
    helpPanel,
    helpPanelIndex,
    languagePanel,
    languagePanelIndex,
    modelPanelIndex,
    trackPanel,
    trackPanelIndex,
    extensionPanel,
    extensionPanelIndex,
    extensionInputFocused,
    memoryPanel,
    memoryPanelIndex,
    memorySearchQuery,
    memoryEditor,
    activeRegion,
    miniSnapshotRevision,
    miniLayout,
    spotifyImmersiveLayout,
    terminalSpace,
    agentWorking,
    streamingMessage,
    language = "en",
}: {
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    inputPlaceholder: string;
    inputMask?: string;
    inputFocus: boolean;
    inputRevision: number;
    player: PlayerState;
    coverUrl: string | null;
    coverPattern: CoverPatternPayload | null;
    confirm: ConfirmState;
    confirmIndex: number;
    spotifyMode: SpotifyModeState;
    providerMode: ProviderModeState;
    spotifySetup: SpotifySetupState;
    authSetup: AuthSetupState;
    modelStatus: string | null;
    slashSuggestions: SlashCommandSuggestion[];
    slashIndex: number;
    helpPanel: HelpPanelState;
    helpPanelIndex: number;
    languagePanel: LanguagePanelState;
    languagePanelIndex: number;
    modelPanelIndex: number;
    trackPanel: TrackPanelState;
    trackPanelIndex: number;
    extensionPanel: ExtensionPanelState;
    extensionPanelIndex: number;
    extensionInputFocused: boolean;
    memoryPanel: MemoryPanelState;
    memoryPanelIndex: number;
    memorySearchQuery: string;
    memoryEditor: { mode: "search" | "add" | "edit" | "setting"; value: string; settingKey?: string } | null;
    activeRegion: ShellRegion;
    miniSnapshotRevision: number;
    miniLayout: MiniPlayerLayout;
    spotifyImmersiveLayout: SpotifyImmersiveLayout;
    terminalSpace: TerminalSpace;
    agentWorking: boolean;
    streamingMessage: ChatMessageItem | null;
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

    if (activeRegion === "spotifyImmersive" || activeRegion === "providerImmersive") {
        return (
            <ProviderImmersiveRegion
                player={player}
                spotifyMode={spotifyMode}
                providerMode={providerMode}
                spotifyImmersiveLayout={spotifyImmersiveLayout}
            />
        );
    }

    if (activeRegion === "trackPanel" && trackPanel) {
        return (
            <TrackPanelOverlay
                trackPanel={trackPanel}
                selectedIndex={trackPanelIndex}
                panelWidth={Math.max(3, Math.floor(terminalSpace.columns ?? 80))}
                spotifyTheme={spotifyMode.enabled}
                language={language}
            />
        );
    }

    if (extensionPanel) {
        return (
            <ExtensionPanelOverlay
                panel={extensionPanel}
                selectedIndex={extensionPanelIndex}
                width={Math.max(3, Math.floor(terminalSpace.columns ?? 80) - 2)}
                input={input}
                setInput={setInput}
                onSubmit={onSubmit}
                inputFocus={extensionPanel.view === "setup" && extensionInputFocused}
            />
        );
    }

    return (
        <DynamicTail
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
            providerMode={providerMode}
            spotifySetup={spotifySetup}
            authSetup={authSetup}
            modelStatus={modelStatus}
            slashSuggestions={slashSuggestions}
            slashIndex={slashIndex}
            helpPanel={helpPanel}
            helpPanelIndex={helpPanelIndex}
            languagePanel={languagePanel}
            languagePanelIndex={languagePanelIndex}
            modelPanelIndex={modelPanelIndex}
            memoryPanel={activeRegion === "memoryPanel" ? memoryPanel : null}
            memoryPanelIndex={memoryPanelIndex}
            memorySearchQuery={memorySearchQuery}
            memoryEditor={memoryEditor}
            terminalColumns={terminalSpace.columns}
            agentWorking={agentWorking}
            streamingMessage={streamingMessage}
            language={language}
        />
    );
};

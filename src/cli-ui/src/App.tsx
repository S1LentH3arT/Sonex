import React, { useState } from 'react';
import { Box, useApp, useInput, useStdin } from 'ink';
import { completeSlashCommand, hasSlashCommandArguments, matchingSlashCommand, slashCommandSuggestions, spotifyModeSlashCommands, unknownSlashCommandMessage } from './commands.js';
import { getSelectableConfirmChoices } from './confirm-choice.js';
import { selectedHelpPanelCommand } from './command-panel.js';
import { API_NOT_RUNNING_DETAIL, API_NOT_RUNNING_MESSAGE, DEFAULT_CONFIRM_CHOICES, FALLBACK_MODEL_NAME, wsUrl } from './constants.js';
import { CommittedTranscript, DynamicShell, HeaderFrame, isGenericAuthSetup, LoginScreen } from './components.js';
import { ExtensionPanelOverlay } from './extension-panel.js';
import { useSonexSocket } from './hooks.js';
import { chatMessagesForTranscript, createInfoBannerItem } from './info-banner.js';
import { applyLanguageToServerEvent, helpCommandsForLanguage, localizeSlashCommands, OFFICIAL_UI_LANGUAGE, t } from './i18n.js';
import { LAUNCH_PREPARING_INTERVAL_MS, launchPreparingText } from './launch-preparing.js';
import { resolveChatHeaderVariant, resolveMiniPlayerLayout, resolveSpotifyImmersiveLayout, type ShellRegion, type TerminalSize } from './layout.js';
import { shouldRefreshMiniSnapshot, usePlaybackProgressWriter, usePlaybackStatusIconWriter } from './mini-progress-writer.js';
import { formatModelStatus } from './model-status.js';
import { filterModelChoices } from './model-selection.js';
import { resolveLoginProviderSelectionIndex } from './login-navigation.js';
import { isLocalPlaybackShortcutSource, isSpotifyPlaybackShortcutSource, playbackCommandForShortcut, playbackShortcutFromInput } from './playback-keymap.js';
import type { TerminalSurfaceController } from './terminal-surface.js';
import { markQueuedTracks } from './track-panel.js';
import { TEXT_STREAM_INTERVAL_MS, nextTextStreamOffset, streamedChatMessage, textStreamUnits } from './text-stream.js';
import { allTranscriptItems, classifyServerEventForTranscript, createTranscriptState, transcriptReducer, type TranscriptPresentation } from './transcript.js';
import { initialShellState, planShellSurfaceTransition, reduceShellState, surfaceForShellRegion, type ShellStateAction } from './shell-state.js';
import { createInitialRuntimeState, reduceRuntimeState, type RuntimeAction } from './runtime-state.js';
import { resolveInputRoute } from './input-routing.js';
import { initialProviderState, reduceProviderState, type ProviderAction } from './provider-state.js';
import { planPanelLifecycle, type PanelLifecycleTrigger } from './panel-lifecycle.js';
import type { AuthRuntimeState, ChatItem, ChatMessageItem, ConfirmState, CoverPatternEvent, ExtensionPanelState, HelpPanelState, LanguagePanelState, MemoryPanelState, PlayerState, ProviderModeState, SessionTokenUsage, SpotifyModeState, TrackPanelState, TrackPanelTrack, TrackSummary, ServerEvent, SlashCommandSuggestion, UiLanguage } from './types.js';
import { TOKEN_USAGE_ANIMATION_INTERVAL_MS, nextAnimatedTokenUsage } from './usage-animation.js';

type InkInputKey = {
    ctrl?: boolean;
    meta?: boolean;
};

type ActiveTextStream = {
    id: number;
    item: ChatMessageItem;
    units: string[];
    visibleUnitCount: number;
    presentation: TranscriptPresentation;
};

const RUNTIME_WORKING_DIRECTORY = process.env.SONEX_LAUNCH_CWD?.trim() || process.cwd();

const isTrackPanelQueueShortcut = (inputKey: string, key: InkInputKey): boolean => {
    return Boolean(key.ctrl && (inputKey === "\x01" || inputKey.toLowerCase() === "a"));
};

export const App: React.FC<{
    terminalSurface: TerminalSurfaceController;
    terminalStdout: NodeJS.WriteStream;
}> = ({ terminalSurface, terminalStdout: stdout }) => {
    const { exit } = useApp();
    const { isRawModeSupported } = useStdin();
    const rawModeAvailable = Boolean(isRawModeSupported && typeof process.stdin.setRawMode === "function");
    const [language] = useState<UiLanguage>(OFFICIAL_UI_LANGUAGE);
    const [input, setInput] = useState("");
    const [inputRevision, setInputRevision] = useState(0);
    const [runtimeState, dispatchRuntimeState] = React.useReducer(
        reduceRuntimeState,
        undefined,
        () => createInitialRuntimeState(t(OFFICIAL_UI_LANGUAGE, "status.snoozing")),
    );
    const { sessionId, tokenUsage, agentWorkingTurnId, activityItems, statusText, launchPreparing, recommendInputLocked } = runtimeState;
    const [displayedTokenUsage, setDisplayedTokenUsage] = useState<SessionTokenUsage>({ inputTokens: 0, outputTokens: 0 });
    const [activeTextStream, setActiveTextStream] = useState<ActiveTextStream | null>(null);
    const [transcript, dispatchTranscript] = React.useReducer(
        transcriptReducer,
        undefined,
        createTranscriptState,
    );
    const [queueItems, setQueueItems] = useState<TrackPanelTrack[]>([]);
    const [searchItems, setSearchItems] = useState<TrackSummary[]>([]);
    const [trackPanel, setTrackPanel] = useState<TrackPanelState>(null);
    const [memoryPanel, setMemoryPanel] = useState<MemoryPanelState>(null);
    const [extensionPanel, setExtensionPanel] = useState<ExtensionPanelState>(null);
    const [extensionPanelIndex, setExtensionPanelIndex] = useState(0);
    const [extensionInputFocused, setExtensionInputFocused] = useState(false);
    const [memorySearchQuery, setMemorySearchQuery] = useState("");
    const [memoryEditor, setMemoryEditor] = useState<{
        mode: "search" | "add" | "edit" | "setting";
        value: string;
        settingKey?: string;
    } | null>(null);
    const [player, setPlayer] = useState<PlayerState>({ name: "-", artist: "-", album: "-", duration_ms: 0, progress_ms: 0, is_playing: false });
    const [launchPreparingFrame, setLaunchPreparingFrame] = useState(0);
    const [coverUrl, setCoverUrl] = useState<string | null>(null);
    const [coverPattern, setCoverPattern] = useState<CoverPatternEvent | null>(null);
    const coverUrlRef = React.useRef<string | null>(null);
    const [confirm, setConfirm] = useState<ConfirmState>(null);
    const [confirmIndex, setConfirmIndex] = useState(0); // 0=Yes, 1=No
    const [providerState, dispatchProviderState] = React.useReducer(reduceProviderState, initialProviderState);
    const { spotifyMode, providerMode, spotifySetup, authSetup } = providerState;
    const [authState, setAuthState] = useState<AuthRuntimeState>({
        ready: false,
        provider: "openai",
        model: FALLBACK_MODEL_NAME,
        auth_type: "none",
        credential_source: "pending",
    });
    const [shellState, dispatchShellState] = React.useReducer(reduceShellState, initialShellState);
    const activeRegion = shellState.region;
    const playbackSessionActive = shellState.playbackSessionActive;
    const [miniSnapshotRevision, setMiniSnapshotRevision] = useState(0);
    const [terminalSize, setTerminalSize] = useState<TerminalSize>({
        columns: stdout.columns ?? null,
        rows: stdout.rows ?? null,
    });
    const [slashIndex, setSlashIndex] = useState(0);
    const [slashMenuDismissedFor, setSlashMenuDismissedFor] = useState<string | null>(null);
    const [isExiting, setIsExiting] = useState(false);
    const [helpPanel, setHelpPanel] = useState<HelpPanelState>(null);
    const [helpPanelIndex, setHelpPanelIndex] = useState(0);
    const [languagePanel, setLanguagePanel] = useState<LanguagePanelState>(null);
    const [languagePanelIndex, setLanguagePanelIndex] = useState(0);
    const [trackPanelIndex, setTrackPanelIndex] = useState(0);
    const [memoryPanelIndex, setMemoryPanelIndex] = useState(0);
    const [loginSelectionIndex, setLoginSelectionIndex] = useState(0);
    const [loginApiKeyInput, setLoginApiKeyInput] = useState("");
    const runtimeStateRef = React.useRef(runtimeState);
    const providerStateRef = React.useRef(providerState);
    const shellStateRef = React.useRef(shellState);
    const playerRef = React.useRef<PlayerState>(player);
    const confirmRef = React.useRef<ConfirmState>(null);
    const dismissedConfirmIdsRef = React.useRef(new Set<string>());
    const spotifyModeRef = React.useRef<SpotifyModeState>(spotifyMode);
    const providerModeRef = React.useRef<ProviderModeState>(providerMode);
    const spotifySetupActiveRef = React.useRef(false);
    const authSetupActiveRef = React.useRef(false);
    const slashMenuActiveRef = React.useRef(false);
    const sessionIdRef = React.useRef<string | null>(null);
    const startupInfoCapturedRef = React.useRef(false);
    const activeTextStreamRef = React.useRef<ActiveTextStream | null>(null);
    const nextTextStreamIdRef = React.useRef(0);
    const isModelPanelActive = authSetup?.active && authSetup.step === "model";
    const isLoginScreenActive = isGenericAuthSetup(authSetup) && !isModelPanelActive;
    const extensionSetupInput = extensionPanel?.view === "setup" ? extensionPanel.setup?.input : null;
    const authInterfaceActive = Boolean(authSetup?.active || spotifySetup?.active);
    const showFixedHeader = activeRegion === "chat" && authInterfaceActive && !isLoginScreenActive;
    const slashSuggestions = authSetup?.active || spotifySetup?.active || languagePanel?.active || extensionPanel
        ? []
        : spotifyMode.enabled
            ? spotifyModeSlashCommands(input, language)
            : slashCommandSuggestions(input, language);
    const slashInput = input.trimStart();
    const isSlashInput = slashInput.startsWith("/");
    const isSlashMenuActive = rawModeAvailable && !confirm && isSlashInput && slashMenuDismissedFor !== input && slashSuggestions.length > 0;
    const isUnknownSlashInput = (
        rawModeAvailable
        && activeRegion === "chat"
        && !confirm
        && !authSetup?.active
        && !spotifySetup?.active
        && !helpPanel
        && !languagePanel?.active
        && !recommendInputLocked
        && slashInput.length > 1
        && isSlashInput
        && slashSuggestions.length === 0
        && !matchingSlashCommand(input)
    );
    const selectedSlashCommand = slashSuggestions[Math.min(slashIndex, Math.max(0, slashSuggestions.length - 1))];
    const selectableConfirmChoices = React.useMemo(() => confirm ? getSelectableConfirmChoices(confirm.choices, confirm.tool_name === "provider_mode_exit") : [], [confirm]);
    const selectedConfirmChoice = selectableConfirmChoices[Math.min(confirmIndex, Math.max(0, selectableConfirmChoices.length - 1))] ?? null;
    const selectedConfirmInput = selectedConfirmChoice?.input ?? null;
    const miniVisible = activeRegion === "miniPlayer";
    const spotifyImmersiveVisible = activeRegion === "spotifyImmersive" || activeRegion === "providerImmersive";
    const miniLayout = React.useMemo(() => resolveMiniPlayerLayout(terminalSize), [terminalSize.columns, terminalSize.rows]);
    const spotifyImmersiveLayout = React.useMemo(() => resolveSpotifyImmersiveLayout(terminalSize), [terminalSize.columns, terminalSize.rows]);
    const headerVariant = resolveChatHeaderVariant(terminalSize.columns);
    const transcriptContentWidth = Math.max(1, (terminalSize.columns ?? 80) - 4);
    const dynamicSurfaceHeight = terminalSize.rows === null
        ? undefined
        : Math.max(0, terminalSize.rows - 1);
    const transcriptPresentation = React.useMemo(() => ({
        contentWidth: transcriptContentWidth,
        headerVariant,
        language,
    }), [headerVariant, language, transcriptContentWidth]);
    const modelStatus = formatModelStatus(authState, displayedTokenUsage);
    const streamingMessage = React.useMemo<ChatMessageItem | null>(() => {
        if (!activeTextStream) return null;
        return streamedChatMessage(
            activeTextStream.item,
            activeTextStream.units,
            activeTextStream.visibleUnitCount,
        );
    }, [activeTextStream]);
    const baseLanguageChoices = React.useMemo<UiLanguage[]>(() => ["en", "zh-CN"], []);
    const languageChoices = React.useMemo<UiLanguage[]>(
        () => [language, ...baseLanguageChoices.filter((choice) => choice !== language)],
        [baseLanguageChoices, language],
    );

    React.useEffect(() => {
        playerRef.current = player;
    }, [player]);

    React.useEffect(() => {
        confirmRef.current = confirm;
    }, [confirm]);

    React.useEffect(() => {
        slashMenuActiveRef.current = isSlashMenuActive;
    }, [isSlashMenuActive]);

    React.useEffect(() => {
        let resizeTimer: ReturnType<typeof setTimeout> | null = null;
        const updateTerminalSize = () => {
            if (resizeTimer) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                const nextSize = {
                    columns: stdout.columns ?? null,
                    rows: stdout.rows ?? null,
                };
                const updateSize = () => {
                    setTerminalSize(nextSize);
                    if (shellStateRef.current.region === "miniPlayer" && shouldRefreshMiniSnapshot("resize")) {
                        setMiniSnapshotRevision((prev) => prev + 1);
                    }
                };
                if (surfaceForShellRegion(shellStateRef.current.region) === "main") {
                    updateSize();
                } else {
                    terminalSurface.transition("alternate", updateSize);
                }
            }, 80);
        };

        const initializeTerminalSize = () => {
            setTerminalSize({
                columns: stdout.columns ?? null,
                rows: stdout.rows ?? null,
            });
        };

        initializeTerminalSize();
        stdout.on("resize", updateTerminalSize);
        return () => {
            if (resizeTimer) clearTimeout(resizeTimer);
            stdout.off("resize", updateTerminalSize);
        };
    }, [stdout, terminalSurface]);

    const finishActiveTextStream = React.useCallback(() => {
        const active = activeTextStreamRef.current;
        if (!active) return;
        activeTextStreamRef.current = null;
        setActiveTextStream(null);
        dispatchTranscript({
            type: "commit",
            items: [active.item],
            presentation: active.presentation,
        });
    }, []);

    const commitItems = React.useCallback((items: ChatItem[]) => {
        if (items.length === 0) return;
        finishActiveTextStream();
        dispatchTranscript({ type: "commit", items, presentation: transcriptPresentation });
    }, [finishActiveTextStream, transcriptPresentation]);

    const startTextStream = React.useCallback((item: ChatMessageItem) => {
        finishActiveTextStream();
        const units = textStreamUnits(item.content);
        if (units.length === 0) {
            dispatchTranscript({ type: "commit", items: [item], presentation: transcriptPresentation });
            return;
        }
        const active: ActiveTextStream = {
            id: nextTextStreamIdRef.current,
            item,
            units,
            visibleUnitCount: nextTextStreamOffset(0, units.length),
            presentation: transcriptPresentation,
        };
        nextTextStreamIdRef.current += 1;
        activeTextStreamRef.current = active;
        setActiveTextStream(active);
    }, [finishActiveTextStream, transcriptPresentation]);

    React.useEffect(() => {
        if (!activeTextStream) return;
        if (activeTextStream.visibleUnitCount >= activeTextStream.units.length) {
            finishActiveTextStream();
            return;
        }

        const timer = setTimeout(() => {
            setActiveTextStream((current) => {
                if (!current || current.id !== activeTextStream.id) return current;
                const next = {
                    ...current,
                    visibleUnitCount: nextTextStreamOffset(current.visibleUnitCount, current.units.length),
                };
                activeTextStreamRef.current = next;
                return next;
            });
        }, TEXT_STREAM_INTERVAL_MS);
        return () => clearTimeout(timer);
    }, [activeTextStream, finishActiveTextStream]);

    const applyShellAction = React.useCallback((action: ShellStateAction) => {
        const nextState = reduceShellState(shellStateRef.current, action);
        shellStateRef.current = nextState;
        dispatchShellState({ type: "replace", state: nextState });
    }, []);

    const applyRuntimeAction = React.useCallback((action: RuntimeAction) => {
        const nextState = reduceRuntimeState(runtimeStateRef.current, action);
        runtimeStateRef.current = nextState;
        if (action.type === "event" && action.event.type === "session_state") {
            sessionIdRef.current = action.event.session_id;
        }
        dispatchRuntimeState({ type: "replace", state: nextState });
    }, []);

    const applyProviderAction = React.useCallback((action: ProviderAction) => {
        const nextState = reduceProviderState(providerStateRef.current, action);
        providerStateRef.current = nextState;
        spotifyModeRef.current = nextState.spotifyMode;
        providerModeRef.current = nextState.providerMode;
        spotifySetupActiveRef.current = Boolean(nextState.spotifySetup?.active);
        authSetupActiveRef.current = Boolean(nextState.authSetup?.active);
        dispatchProviderState({ type: "replace", state: nextState });
    }, []);

    const switchRegion = React.useCallback((nextRegion: ShellRegion) => {
        const transition = planShellSurfaceTransition(shellStateRef.current.region, nextRegion);
        if (!transition.changed) return;
        const nextSurface = transition.target;
        terminalSurface.transition(nextSurface, (surface) => {
            dispatchTranscript({ type: "setSurface", surface });
            applyShellAction({ type: "set_region", region: nextRegion });
            if (nextRegion === "miniPlayer" && shouldRefreshMiniSnapshot("region")) {
                setMiniSnapshotRevision((prev) => prev + 1);
            }
        });
    }, [applyShellAction, terminalSurface]);

    usePlaybackProgressWriter({
        enabled: stdout.isTTY === true && (miniVisible || spotifyImmersiveVisible),
        player,
        position: spotifyImmersiveVisible ? spotifyImmersiveLayout.progressSlot : miniLayout.progressSlot,
        stdout,
    });
    usePlaybackStatusIconWriter({
        enabled: stdout.isTTY === true && miniVisible,
        player,
        position: miniLayout.statusIconSlot,
        stdout,
    });

    React.useEffect(() => {
        setSlashIndex((prev) => Math.min(prev, Math.max(0, slashSuggestions.length - 1)));
    }, [slashSuggestions.length]);

    React.useEffect(() => {
        if (!isSlashInput || authSetup?.active || spotifySetup?.active || slashSuggestions.length === 0) {
            setSlashMenuDismissedFor(null);
            setSlashIndex(0);
        }
    }, [authSetup?.active, isSlashInput, slashSuggestions.length, spotifySetup?.active]);

    React.useEffect(() => {
        setLoginApiKeyInput("");
    }, [authSetup?.step, authSetup?.provider]);

    React.useEffect(() => {
        if (!launchPreparing) return;
        const timer = setInterval(() => {
            setLaunchPreparingFrame((prev) => prev + 1);
        }, LAUNCH_PREPARING_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [launchPreparing]);

    const applyPanelLifecycle = React.useCallback((trigger: PanelLifecycleTrigger) => {
        const lifecycle = planPanelLifecycle(trigger);
        for (const panel of lifecycle.close) {
            if (panel === 'track') setTrackPanel(null);
            if (panel === 'memory') setMemoryPanel(null);
            if (panel === 'extension') setExtensionPanel(null);
            if (panel === 'help') setHelpPanel(null);
            if (panel === 'language') setLanguagePanel(null);
        }
        for (const panel of lifecycle.resetSelection) {
            if (panel === 'track') setTrackPanelIndex(0);
            if (panel === 'help') setHelpPanelIndex(0);
        }
    }, []);

    React.useEffect(() => {
        if (
            displayedTokenUsage.inputTokens === tokenUsage.inputTokens
            && displayedTokenUsage.outputTokens === tokenUsage.outputTokens
        ) return;

        const timer = setTimeout(() => {
            setDisplayedTokenUsage((current) => nextAnimatedTokenUsage(current, tokenUsage));
        }, TOKEN_USAGE_ANIMATION_INTERVAL_MS);
        return () => clearTimeout(timer);
    }, [displayedTokenUsage, tokenUsage]);

    const updateInput = React.useCallback((value: string) => {
        if (recommendInputLocked) return;
        const sanitized = value.replace(/\x1B/g, "");
        setInput(sanitized);
        if (sanitized) {
            applyPanelLifecycle("input");
        }
        if (sanitized !== slashMenuDismissedFor) {
            setSlashMenuDismissedFor(null);
        }
    }, [applyPanelLifecycle, recommendInputLocked, slashMenuDismissedFor]);

    const showError = React.useCallback((message: string, detail?: string | null) => {
        const content = detail ? `${message}\n${detail}` : message;
        commitItems([{
            type: "message",
            role: "agent",
            content,
            theme: spotifyModeRef.current.enabled ? "spotify" : undefined,
            tone: "error",
        }]);
    }, [commitItems]);

    const appendUnknownCommandWarning = React.useCallback((value: string) => {
        commitItems([{
            type: "message",
            role: "agent",
            content: unknownSlashCommandMessage(value),
            tone: "warning",
        }]);
    }, [commitItems]);

    const inputPlaceholder = selectedConfirmInput
        ? selectedConfirmInput.placeholder
        : authSetup?.active && authSetup.prompt
            ? authSetup.prompt
            : spotifySetup?.active && spotifySetup.prompt
                ? spotifySetup.prompt
                : extensionSetupInput
                    ? extensionSetupInput.placeholder
                : recommendInputLocked
                    ? t(language, "input.recommendPending")
                    : "";
    const inputMask = authSetup?.active && authSetup.mask
        ? "*"
        : spotifySetup?.active && spotifySetup.mask
            ? "*"
            : extensionSetupInput?.mask
                ? "*"
            : undefined;
    const onEvent = React.useCallback((rawEvent: ServerEvent) => {
        const evt = applyLanguageToServerEvent(rawEvent, language);
        const transcriptClass = classifyServerEventForTranscript(evt);
        if (transcriptClass === "chat" && evt.type === "chat") {
            const item: ChatMessageItem = {
                type: "message",
                role: evt.role,
                content: evt.text,
                theme: evt.theme,
                tone: evt.tone,
                segments: evt.segments,
                document: evt.document,
            };
            if (evt.role === "agent" && evt.stream) {
                startTextStream(item);
                return;
            }
            if (evt.role === "user") {
                finishActiveTextStream();
                dispatchTranscript({
                    type: "receiveUser",
                    item,
                    presentation: transcriptPresentation,
                });
            } else {
                commitItems([item]);
            }
            return;
        }
        if (transcriptClass === "error" && evt.type === "error") {
            showError(evt.message, evt.detail);
            return;
        }

        applyRuntimeAction({ type: "event", event: evt, rawEvent });
        if (evt.type === "spotify_mode" || evt.type === "provider_mode" || evt.type === "spotify_setup" || evt.type === "auth_setup") {
            applyProviderAction({ type: "event", event: evt });
        }

        switch (evt.type) {
            case "session_state":
                break;
            case "usage_state":
                break;
            case "agent_working_state":
                break;
            case "activity":
                if (runtimeStateRef.current.launchPreparing) setLaunchPreparingFrame(0);
                break;
            case "status":
                break;
            case "input_state":
                if (evt.disabled && evt.reason === "recommendation") {
                    setInput("");
                    setInputRevision((prev) => prev + 1);
                    setSlashMenuDismissedFor(null);
                }
                break;
            case "queue":
                setQueueItems(evt.tracks);
                setTrackPanel((current) => current ? { ...current, tracks: markQueuedTracks(current.panel === "queue" ? evt.tracks : current.tracks, evt.tracks) } : current);
                break;
            case "track_panel":
                setTrackPanel({
                    panel: evt.panel,
                    title: evt.title,
                    hint: evt.hint,
                    tracks: markQueuedTracks(evt.tracks, queueItems),
                });
                setTrackPanelIndex(0);
                switchRegion("trackPanel");
                break;
            case "memory_panel":
                setMemoryPanel({
                    view: evt.view,
                    target: evt.target,
                    title: evt.title,
                    hint: evt.hint,
                    readOnly: Boolean(evt.read_only),
                    entries: evt.entries ?? [],
                    settings: evt.settings,
                });
                setMemoryPanelIndex(0);
                setMemorySearchQuery("");
                setMemoryEditor(null);
                switchRegion("memoryPanel");
                break;
            case "extension_panel": {
                const selected = evt.selected_extension ?? null;
                setExtensionPanel({
                    view: evt.view,
                    title: evt.title,
                    hint: evt.hint,
                    selectedExtension: selected,
                    extensions: evt.extensions,
                    detail: evt.detail,
                    setup: evt.setup,
                });
                const nextIndex = evt.view === "detail"
                    ? (() => {
                        const detailActions = evt.detail?.actions ?? [];
                        const focused = evt.detail?.selected_action;
                        const focusedIndex = focused ? detailActions.indexOf(focused) : 0;
                        return focusedIndex >= 0 ? focusedIndex : 0;
                    })()
                    : evt.view === "setup"
                        ? evt.setup?.dependencies && evt.setup.selected_dependency
                            ? Math.max(0, evt.setup.dependencies.findIndex((dependency) => dependency.id === evt.setup?.selected_dependency))
                            : 0
                    : selected
                        ? evt.extensions.findIndex((extension) => extension.id === selected)
                        : 0;
                setExtensionPanelIndex(Math.max(0, nextIndex));
                setExtensionInputFocused(false);
                applyPanelLifecycle("extension_event");
                break;
            }
            case "search_results": {
                setSearchItems(evt.tracks);
                const first = evt.tracks[0];
                if (first) {
                    setPlayer({
                        name: first.title || first.name || "-",
                        artist: first.artist || "-",
                        album: first.album || "-",
                        duration_ms: first.duration_ms || 0,
                        progress_ms: 0,
                        is_playing: false,
                    });
                    coverUrlRef.current = first.album_cover_url ?? null;
                    setCoverUrl(first.album_cover_url ?? null);
                    setCoverPattern(null);
                }
                break;
            }
            case "player":
                setPlayer(evt.state);
                const nextShellState = reduceShellState(shellStateRef.current, {
                    type: "player_event",
                    player: evt.state,
                    spotifyModeEnabled: false,
                    providerMode: providerModeRef.current.enabled && providerModeRef.current.provider !== "normal"
                        ? providerModeRef.current.provider
                        : null,
                });
                if (nextShellState.region !== shellStateRef.current.region) {
                    switchRegion(nextShellState.region);
                }
                applyShellAction({ type: "replace", state: nextShellState });
                break;
            case "spotify_mode":
                if (!evt.enabled && shellStateRef.current.region === "spotifyImmersive") {
                    switchRegion("chat");
                }
                break;
            case "provider_mode": {
                if (!evt.enabled && shellStateRef.current.region === "providerImmersive") {
                    switchRegion("chat");
                }
                break;
            }
            case "cover":
                coverUrlRef.current = evt.url;
                setCoverUrl(evt.url);
                setCoverPattern(null);
                break;
            case "cover_pattern":
                setCoverPattern((prev) => {
                    if (evt.source_url !== coverUrlRef.current) return prev;
                    return evt;
                });
                break;
            case "cover_pattern_unavailable":
                setCoverPattern((prev) => {
                    if (evt.source_url !== coverUrlRef.current) return prev;
                    return {
                        type: "cover_pattern",
                        source_url: evt.source_url,
                        palette: [],
                        variants: {},
                        unavailable_reason: evt.reason,
                    };
                });
                break;
            case "confirm":
                if (dismissedConfirmIdsRef.current.has(evt.id)) {
                    break;
                }
                setInput("");
                switchRegion("chat");
                setConfirm({
                    id: evt.id,
                    tool_name: evt.tool_name,
                    tool_args: evt.tool_args ?? {},
                    message: evt.message || `Confirm ${evt.tool_name}`,
                    warning: evt.warning,
                    hide_hint: evt.hide_hint === true,
                    choices: evt.choices && evt.choices.length > 0 ? evt.choices : DEFAULT_CONFIRM_CHOICES,
                    variant: evt.variant,
                    commands: evt.commands ?? [],
                    page_index: evt.page_index,
                    page_count: evt.page_count,
                });
                if (evt.tool_args?.preserve_selection !== true) {
                    setConfirmIndex(0);
                }
                break;
            case "confirm_dismiss": {
                const currentConfirm = confirmRef.current;
                dismissedConfirmIdsRef.current.add(evt.id);
                if (currentConfirm?.id === evt.id) {
                    setConfirm(null);
                }
                break;
            }
            case "spotify_setup":
                applyPanelLifecycle("setup_event");
                if (evt.active !== false) {
                    switchRegion("chat");
                }
                break;
            case "auth_setup":
                applyPanelLifecycle("setup_event");
                if (evt.active === false && evt.step === "model") {
                    setInput("");
                    break;
                }
                if (evt.active !== false) {
                    switchRegion("chat");
                }
                if (evt.step === "provider") {
                    const providers = evt.providers ?? [];
                    setLoginSelectionIndex(resolveLoginProviderSelectionIndex(providers, evt.provider));
                } else {
                    setLoginSelectionIndex(0);
                }
                if (evt.step === "model") {
                    setInput("");
                }
                break;
            case "auth_state":
                const
                    nextAuthState = {
                    ready: evt.ready,
                    provider: evt.provider,
                    model: evt.model,
                    model_label: evt.model_label,
                    auth_type: evt.auth_type,
                    credential_source: evt.credential_source,
                    reason: evt.reason,
                };
                setAuthState(nextAuthState);
                if (!startupInfoCapturedRef.current) {
                    startupInfoCapturedRef.current = true;
                    commitItems([createInfoBannerItem(
                        nextAuthState,
                        RUNTIME_WORKING_DIRECTORY,
                        sessionIdRef.current,
                        { showLogo: true },
                    )]);
                }
                break;
            case "help_panel":
                switchRegion("chat");
                applyPanelLifecycle("help_event");
                setHelpPanel({
                    title: evt.title,
                    hint: evt.hint,
                    commands: helpCommandsForLanguage(evt.commands, language),
                });
                break;
            case "bye":
                setIsExiting(true);
                switchRegion("chat");
                applyPanelLifecycle("bye");
                setTimeout(() => exit(), 80);
                break;
        }
    }, [applyPanelLifecycle, applyRuntimeAction, applyShellAction, commitItems, exit, finishActiveTextStream, language, queueItems, showError, startTextStream, switchRegion, transcriptPresentation]);

    const { send } = useSonexSocket({
        url: wsUrl,
        onEvent,
        onClientError: (message, detail) => showError(
            language === "zh-CN" && message.startsWith("Sonex API is not running")
                ? `${t(language, "api.notRunning.message")}。 ${t(language, "api.notRunning.detail")}`
                : message,
            detail,
        ),
    });

    React.useEffect(() => {
        if (!rawModeAvailable) return;

        const handlePlaybackShortcut = (chunk: Buffer | string) => {
            const action = playbackShortcutFromInput(chunk.toString("utf8"));
            if (!action) return;
            if (!shellStateRef.current.playbackSessionActive) return;
            if (confirmRef.current) return;
            if (spotifySetupActiveRef.current) return;
            if (authSetupActiveRef.current) return;
            if (slashMenuActiveRef.current) return;

            const localShortcut = shellStateRef.current.region === "miniPlayer"
                && isLocalPlaybackShortcutSource(playerRef.current);
            const spotifyShortcut = shellStateRef.current.region === "spotifyImmersive"
                && spotifyModeRef.current.enabled
                && action === "togglePlayback"
                && isSpotifyPlaybackShortcutSource(playerRef.current);
            const providerShortcut = shellStateRef.current.region === "providerImmersive"
                && providerModeRef.current.enabled
                && action === "togglePlayback"
                && providerModeRef.current.provider === "spotify"
                && isSpotifyPlaybackShortcutSource(playerRef.current);
            if (!localShortcut && !spotifyShortcut && !providerShortcut) return;

            const command = playbackCommandForShortcut(action, playerRef.current);
            send({ type: "internal_command", text: command });
        };

        process.stdin.on("data", handlePlaybackShortcut);
        return () => {
            process.stdin.off("data", handlePlaybackShortcut);
        };
    }, [rawModeAvailable, send]);

    const requestSafeExit = React.useCallback((reason: string) => {
        if (isExiting) return;
        setIsExiting(true);
        setInput("");
        switchRegion("chat");
        setSlashMenuDismissedFor(null);
        applyPanelLifecycle("safe_exit");
        applyRuntimeAction({ type: "set_status", text: t(language, "status.saving") });
        applyRuntimeAction({ type: "event", event: {
            type: "activity",
            id: "bye_saving",
            kind: "status",
            title: "Saving session",
            detail: "Writing transcript before exit.",
            status: "pending",
            timestamp: Date.now(),
        } });

        const transcriptItems = allTranscriptItems(transcript);
        const sent = send({ type: "bye", messages: chatMessagesForTranscript(transcriptItems), reason });
        if (!sent) {
            setIsExiting(false);
            showError(
                "Session could not be saved before exit.",
                "The Sonex API connection is not open.",
            );
        }
    }, [applyPanelLifecycle, applyRuntimeAction, isExiting, language, send, showError, switchRegion, transcript]);

    const loginChoices = authSetup?.step === "provider"
        ? authSetup.providers ?? []
        : authSetup?.step === "method"
            ? authSetup.methods ?? []
            : authSetup?.step === "model"
                ? authSetup.models ?? []
                : [];
    const submitLoginChoice = React.useCallback(() => {
        if (!authSetup?.active) return;
        const choices = authSetup.step === "provider"
            ? authSetup.providers ?? []
            : authSetup.step === "method"
                ? authSetup.methods ?? []
                : authSetup.step === "model"
                    ? authSetup.models ?? []
                    : [];
        const choice = choices[Math.min(loginSelectionIndex, Math.max(0, choices.length - 1))];
        if (choice) {
            send({ type: "auth_setup_input", value: choice.value });
        }
    }, [authSetup, loginSelectionIndex, send]);

    const submitLoginApiKey = React.useCallback((value: string) => {
        const text = value.trim();
        if (!text) return;
        setLoginApiKeyInput("");
        send({ type: "auth_setup_input", value: text });
    }, [send]);

    const applySlashCompletion = React.useCallback((command: SlashCommandSuggestion) => {
        setInput(completeSlashCommand(command));
        setInputRevision((prev) => prev + 1);
        setSlashMenuDismissedFor(null);
    }, []);

    const submitInput = React.useCallback((value: string) => {
        if (recommendInputLocked) return;
        const route = resolveInputRoute(value, {
            confirm,
            selectedConfirmChoice,
            selectableConfirmChoices,
            extensionPanelActive: Boolean(extensionPanel),
            extensionInputFocused,
            extensionSetupInput: extensionSetupInput ?? null,
            authSetupActive: Boolean(authSetup?.active),
            spotifySetupActive: Boolean(spotifySetup?.active),
            selectedSlashCommand,
        });
        if (route.type === "empty") return;
        finishActiveTextStream();

        switch (route.type) {
            case "ignore":
                return;
            case "confirm":
                setInput("");
                send({ type: "confirm_result", id: confirm!.id, decision: route.decision });
                setConfirm(null);
                return;
            case "extension_input":
                setInput("");
                setExtensionInputFocused(false);
                send({ type: "extension_panel_input", value: route.value });
                return;
            case "safe_exit":
                requestSafeExit(route.reason);
                return;
            case "info":
                setInput("");
                setSlashMenuDismissedFor(null);
                applyPanelLifecycle("info");
                commitItems([createInfoBannerItem(authState, RUNTIME_WORKING_DIRECTORY, sessionIdRef.current)]);
                return;
            case "slash_completion":
                applySlashCompletion(route.command);
                setSlashIndex(0);
                return;
            case "unknown_slash":
                setInput("");
                setSlashMenuDismissedFor(null);
                appendUnknownCommandWarning(route.value);
                return;
            case "setup_input":
                setInput("");
                setSlashMenuDismissedFor(null);
                setLanguagePanel(null);
                send({ type: route.channel === "spotify" ? "setup_input" : "auth_setup_input", value: route.value });
                return;
            case "user_input": {
                setInput("");
                setSlashMenuDismissedFor(null);
                if (route.command?.name !== "help") {
                    setHelpPanel(null);
                    setHelpPanelIndex(0);
                }
                setLanguagePanel(null);
                const sent = send({ type: "user_input", text: route.value });
                if (!sent) showError(API_NOT_RUNNING_MESSAGE, API_NOT_RUNNING_DETAIL);
                return;
            }
        }
    }, [applyPanelLifecycle, applySlashCompletion, appendUnknownCommandWarning, authState, commitItems, confirm, extensionInputFocused, extensionPanel, extensionSetupInput, finishActiveTextStream, recommendInputLocked, requestSafeExit, selectableConfirmChoices, selectedConfirmChoice, selectedSlashCommand, send, showError, authSetup?.active, spotifySetup?.active]);

    useInput((inputKey, key) => {
        if (!extensionPanel) return;
        if (key.escape) {
            setExtensionInputFocused(false);
            setInput("");
            if (extensionPanel.view === "list") {
                setExtensionPanel(null);
                send({ type: "extension_panel_action", action: "close" });
            } else {
                send({
                    type: "extension_panel_action",
                    action: "back",
                    extension_id: extensionPanel.selectedExtension ?? undefined,
                });
            }
            return;
        }
        if (extensionPanel.view === "list") {
            if (key.upArrow) {
                setExtensionPanelIndex((prev) => (prev - 1 + extensionPanel.extensions.length) % extensionPanel.extensions.length);
            } else if (key.downArrow) {
                setExtensionPanelIndex((prev) => (prev + 1) % extensionPanel.extensions.length);
            } else if (key.return) {
                const selected = extensionPanel.extensions[extensionPanelIndex];
                if (selected) send({ type: "extension_panel_action", action: "open_detail", extension_id: selected.id });
            }
            return;
        }
        if (extensionPanel.view === "setup") {
            if (extensionPanel.setup?.dependencies && extensionPanel.setup.dependencies.length > 0) {
                if (key.upArrow) {
                    setExtensionPanelIndex((prev) => (prev - 1 + extensionPanel.setup!.dependencies!.length) % extensionPanel.setup!.dependencies!.length);
                } else if (key.downArrow) {
                    setExtensionPanelIndex((prev) => (prev + 1) % extensionPanel.setup!.dependencies!.length);
                } else if (key.return) {
                    const dependency = extensionPanel.setup.dependencies[extensionPanelIndex];
                    if (dependency && dependency.state !== "installed") {
                        send({ type: "extension_panel_action", action: "install_dependency", extension_id: extensionPanel.selectedExtension ?? undefined, dependency_id: dependency.id });
                    }
                }
            } else if (key.leftArrow) {
                send({ type: "extension_panel_action", action: "prev_page", extension_id: extensionPanel.selectedExtension ?? undefined });
            } else if (key.rightArrow) {
                send({ type: "extension_panel_action", action: "next_page", extension_id: extensionPanel.selectedExtension ?? undefined });
            } else if (key.return) {
                if (extensionPanel.setup?.input && !extensionInputFocused) {
                    setExtensionInputFocused(true);
                } else if (!extensionPanel.setup?.input) {
                    send({ type: "extension_panel_input", value: "" });
                }
            }
            return;
        }
        const detail = extensionPanel.detail;
        const extension = extensionPanel.extensions.find((item) => item.id === extensionPanel.selectedExtension);
        if (!detail || !extension) return;
        const actions = detail.actions ?? [];
        if (actions.length === 0) return;
        if (key.upArrow) {
            setExtensionPanelIndex((prev) => (prev - 1 + actions.length) % actions.length);
        } else if (key.downArrow) {
            setExtensionPanelIndex((prev) => (prev + 1) % actions.length);
        } else if (key.return) {
            const selectedAction = actions[Math.min(extensionPanelIndex, Math.max(0, actions.length - 1))];
            if (selectedAction) send({
                type: "extension_panel_action",
                action: selectedAction,
                extension_id: extension.id,
                token: selectedAction === "confirm_reset" || selectedAction === "confirm_restart" ? detail.armed_token : undefined,
                revision: detail.revision,
            });
        }
    }, { isActive: rawModeAvailable && Boolean(extensionPanel) && !confirm });

    useInput((inputKey, key) => {
        if (key.ctrl && inputKey === "c") {
            requestSafeExit("ctrl_c");
        }
    }, { isActive: rawModeAvailable });

    useInput((inputKey, key) => {
        if (!isLoginScreenActive) return;
        if (key.escape) {
            applyProviderAction({ type: "clear_auth_setup" });
            setLoginSelectionIndex(0);
            setLoginApiKeyInput("");
            send({ type: "auth_setup_input", value: "__cancel__" });
            return;
        }
        if (authSetup?.step === "api_key") return;

        if ((authSetup?.step === "provider" || authSetup?.step === "method") && loginChoices.length > 0) {
            if (key.upArrow) {
                setLoginSelectionIndex((prev) => (prev - 1 + loginChoices.length) % loginChoices.length);
            } else if (key.downArrow) {
                setLoginSelectionIndex((prev) => (prev + 1) % loginChoices.length);
            } else if (key.return) {
                submitLoginChoice();
            }
        }
    }, { isActive: rawModeAvailable && isLoginScreenActive });

    useInput((_inputKey, key) => {
        if (!spotifySetup?.active || !key.escape) return;
        applyProviderAction({ type: "clear_spotify_setup" });
        setInput("");
        send({ type: "setup_input", value: "__cancel__" });
    }, { isActive: rawModeAvailable && Boolean(spotifySetup?.active) });

    useInput((inputKey, key) => {
        if (!isModelPanelActive) return;
        const choices = filterModelChoices(authSetup?.models ?? [], input);

        if (key.upArrow && choices.length > 0) {
            setLoginSelectionIndex((prev) => (prev - 1 + choices.length) % choices.length);
        } else if (key.downArrow && choices.length > 0) {
            setLoginSelectionIndex((prev) => (prev + 1) % choices.length);
        } else if (key.return && choices.length > 0) {
            const choice = choices[Math.min(loginSelectionIndex, Math.max(0, choices.length - 1))];
            if (choice) {
                send({ type: "auth_setup_input", value: choice.value });
                setInput("");
            }
        } else if (key.escape) {
            applyProviderAction({ type: "clear_auth_setup" });
            setLoginSelectionIndex(0);
            setInput("");
            send({ type: "auth_setup_input", value: "__cancel__" });
        } else if (key.backspace || key.delete) {
            setInput((previous) => previous.slice(0, -1));
            setLoginSelectionIndex(0);
        } else if (
            inputKey
            && !key.ctrl
            && !key.meta
            && !key.return
            && !key.upArrow
            && !key.downArrow
        ) {
            setInput((previous) => previous + inputKey);
            setLoginSelectionIndex(0);
        }
    }, { isActive: rawModeAvailable && Boolean(isModelPanelActive) });

    useInput((inputKey, key) => {
        if (!isSlashMenuActive || !selectedSlashCommand) return;

        if (key.upArrow) {
            setSlashIndex((prev) => (prev - 1 + slashSuggestions.length) % slashSuggestions.length);
        } else if (key.downArrow) {
            setSlashIndex((prev) => (prev + 1) % slashSuggestions.length);
        } else if (key.tab || inputKey === "\t") {
            applySlashCompletion(selectedSlashCommand);
        } else if (key.return) {
            const command = matchingSlashCommand(input);
            if (!command || (command.needsArgument && !hasSlashCommandArguments(input))) {
                applySlashCompletion(selectedSlashCommand);
            }
        } else if (key.escape) {
            setSlashMenuDismissedFor(input);
        }
    }, { isActive: isSlashMenuActive });

    useInput((inputKey, key) => {
        if (!isUnknownSlashInput) return;
        if (key.tab || inputKey === "\t") {
            appendUnknownCommandWarning(input);
        }
    }, { isActive: isUnknownSlashInput });

    useInput((inputKey, key) => {
        if (!languagePanel?.active) return;

        if (key.escape) {
            setLanguagePanel(null);
        }
    }, { isActive: Boolean(languagePanel?.active) && rawModeAvailable });

    useInput((inputKey, key) => {
        if (spotifySetup && spotifySetup.active === false && key.escape) {
            applyProviderAction({ type: "clear_spotify_setup" });
        } else if (authSetup && authSetup.active === false && key.escape) {
            applyProviderAction({ type: "clear_auth_setup" });
        }
    }, { isActive: rawModeAvailable && (Boolean(spotifySetup && spotifySetup.active === false) || Boolean(authSetup && authSetup.active === false)) });

    useInput((inputKey, key) => {
        if (!confirm) return;
        if (key.upArrow) {
            setInput("");
            setConfirmIndex((prev) => Math.max(0, prev - 1));
        } else if (key.downArrow) {
            setInput("");
            setConfirmIndex((prev) => selectableConfirmChoices.length > 0 ? Math.min(selectableConfirmChoices.length - 1, prev + 1) : 0);
        } else if (key.return) {
            if (selectableConfirmChoices.length === 0) return;
            if (selectedConfirmChoice?.input) return;
            send({
                type: "confirm_result",
                id: confirm.id,
                decision: selectedConfirmChoice?.value ?? "allow_once",
            });
            setConfirm(null);
        } else if (key.escape) {
            dismissedConfirmIdsRef.current.add(confirm.id);
            send({ type: "confirm_result", id: confirm.id, decision: "deny" });
            setConfirm(null);
        }
    }, {
        isActive: Boolean(confirm)
            && rawModeAvailable
            && !authSetup?.active
            && !spotifySetup?.active,
    });

    useInput((inputKey, key) => {
        if (!helpPanel || confirm || isSlashMenuActive || languagePanel?.active) return;

        if (key.upArrow && helpPanel.commands.length > 0) {
            setHelpPanelIndex((prev) => (prev - 1 + helpPanel.commands.length) % helpPanel.commands.length);
        } else if (key.downArrow && helpPanel.commands.length > 0) {
            setHelpPanelIndex((prev) => (prev + 1) % helpPanel.commands.length);
        } else if (key.return && helpPanel.commands.length > 0) {
            const selectedHelpPanelItem = selectedHelpPanelCommand(helpPanel.commands, helpPanelIndex);
            const selectedHelpCommand = selectedHelpPanelItem ? matchingSlashCommand(`/${selectedHelpPanelItem.name}`) : null;
            if (selectedHelpCommand) {
                setHelpPanel(null);
                setHelpPanelIndex(0);
                setInput(completeSlashCommand(selectedHelpCommand));
                setInputRevision((prev) => prev + 1);
            }
        } else if (key.escape) {
            setHelpPanel(null);
            setHelpPanelIndex(0);
        }
    }, { isActive: Boolean(helpPanel) && rawModeAvailable && !confirm && !isSlashMenuActive && !languagePanel?.active });

    useInput((inputKey, key) => {
        if (activeRegion !== "trackPanel" || !trackPanel || confirm || isSlashMenuActive || languagePanel?.active || isModelPanelActive) return;
        const selectedTrackPanelTrack = trackPanel.tracks[Math.min(trackPanelIndex, Math.max(0, trackPanel.tracks.length - 1))] ?? null;
        if (key.escape) {
            setTrackPanel(null);
            setTrackPanelIndex(0);
            switchRegion("chat");
        } else if (isTrackPanelQueueShortcut(inputKey, key) && selectedTrackPanelTrack) {
            send({ type: "track_panel_action", action: "queue_add", track: selectedTrackPanelTrack, panel: trackPanel.panel, title: trackPanel.title });
        } else if (key.return && selectedTrackPanelTrack) {
            setTrackPanel(null);
            setTrackPanelIndex(0);
            switchRegion("chat");
            send({ type: "track_panel_action", action: "play", track: selectedTrackPanelTrack, panel: trackPanel.panel, title: trackPanel.title });
        } else if (key.upArrow) {
            setTrackPanelIndex((prev) => Math.max(0, prev - 1));
        } else if (key.downArrow) {
            setTrackPanelIndex((prev) => Math.min(trackPanel.tracks.length - 1, prev + 1));
        }
    }, {
        isActive: activeRegion === "trackPanel"
            && Boolean(trackPanel)
            && rawModeAvailable
            && !confirm
            && !isSlashMenuActive
            && !languagePanel?.active
            && !isModelPanelActive,
    });

    useInput((inputKey, key) => {
        if (activeRegion !== "memoryPanel" || !memoryPanel || confirm) return;
        const visibleEntries = memoryPanel.entries.filter((entry) => entry.content.toLocaleLowerCase().includes(memorySearchQuery.toLocaleLowerCase()));
        const count = memoryPanel.view === "root" ? 2 : memoryPanel.view === "sources" || memoryPanel.view === "format" ? 3 : memoryPanel.view === "settings" ? 8 : visibleEntries.length;
        const selected = visibleEntries[Math.min(memoryPanelIndex, Math.max(0, visibleEntries.length - 1))] ?? null;
        if (memoryEditor) {
            if (key.escape) {
                setMemoryEditor(null);
            } else if (memoryEditor.mode === "search" && key.return) {
                setMemorySearchQuery(memoryEditor.value);
                setMemoryPanelIndex(0);
                setMemoryEditor(null);
            } else if (memoryEditor.mode === "setting" && key.return) {
                const settingValue = memoryEditor.value.trim();
                if (memoryEditor.settingKey && settingValue) {
                    send({
                        type: "memory_panel_action",
                        action: "setting",
                        entry_id: memoryEditor.settingKey,
                        value: settingValue,
                    });
                }
                setMemoryEditor(null);
            } else if (memoryEditor.mode !== "search" && key.ctrl && inputKey.toLowerCase() === "s") {
                if (memoryEditor.value.trim()) {
                    send({
                        type: "memory_panel_action",
                        action: memoryEditor.mode,
                        target: memoryPanel.target ?? undefined,
                        entry_id: memoryEditor.mode === "edit" ? selected?.entry_id : undefined,
                        content: memoryEditor.value,
                    });
                }
                setMemoryEditor(null);
            } else if (memoryEditor.mode !== "search" && memoryEditor.mode !== "setting" && key.return) {
                setMemoryEditor((current) => current ? { ...current, value: `${current.value}\n` } : current);
            } else if (key.backspace || key.delete) {
                setMemoryEditor((current) => current ? { ...current, value: Array.from(current.value).slice(0, -1).join("") } : current);
            } else if (inputKey && !key.ctrl && !key.meta) {
                setMemoryEditor((current) => current ? { ...current, value: current.value + inputKey } : current);
            }
            return;
        }
        if (key.escape) {
            if (memorySearchQuery) {
                setMemorySearchQuery("");
                setMemoryPanelIndex(0);
                return;
            }
            if (memoryPanel.view === "detail") {
                send({ type: "memory_panel_action", action: "open", target: memoryPanel.target ?? undefined });
            } else if (memoryPanel.view === "revisions") {
                send({
                    type: "memory_panel_action",
                    action: "detail",
                    target: memoryPanel.target ?? undefined,
                    entry_id: String(memoryPanel.settings?.entry_id ?? ""),
                });
            } else if (memoryPanel.view === "entries") {
                send({ type: "memory_panel_action", action: "sources" });
            } else if (memoryPanel.view === "sources" || memoryPanel.view === "format") {
                send({ type: "memory_panel_action", action: "root" });
            } else {
                send({ type: "memory_panel_action", action: "close" });
                setMemoryPanel(null);
                switchRegion("chat");
            }
        } else if (key.upArrow) {
            setMemoryPanelIndex((current) => Math.max(0, current - 1));
        } else if (key.downArrow) {
            setMemoryPanelIndex((current) => Math.min(Math.max(0, count - 1), current + 1));
        } else if (key.return) {
            if (memoryPanel.view === "root" && memoryPanelIndex === 0) {
                send({ type: "memory_panel_action", action: "sources" });
            } else if (memoryPanel.view === "root" && memoryPanelIndex === 1) {
                send({ type: "memory_panel_action", action: "format_scopes" });
            } else if (memoryPanel.view === "sources") {
                const target = (["user", "memory", "dump"] as const)[memoryPanelIndex];
                send({ type: "memory_panel_action", action: "open", target });
            } else if (memoryPanel.view === "format") {
                const target = (["user", "memory", "all"] as const)[memoryPanelIndex];
                send({ type: "memory_panel_action", action: "format_confirm", target });
            } else if (memoryPanel.view === "settings" && !memoryPanel.readOnly) {
                const settings = memoryPanel.settings ?? {};
                const keys = [
                    "forget_retention_days", "user_capacity", "memory_capacity", "automatic_forgetting",
                    "idle_threshold_days", "automatic_refinement", "user_refinement_window", "memory_refinement_window",
                ];
                const keyName = keys[memoryPanelIndex];
                if (keyName?.includes("capacity") || keyName?.includes("refinement_window")) {
                    const currentValue = settings[keyName];
                    setMemoryEditor({
                        mode: "setting",
                        settingKey: keyName,
                        value: currentValue == null ? "Unlimited" : String(currentValue),
                    });
                    return;
                }
                const nextValue = keyName === "forget_retention_days"
                    ? ({ 1: 3, 3: 7, 7: 1 } as Record<number, number>)[Number(settings[keyName] ?? 7)]
                    : keyName === "idle_threshold_days"
                        ? ({ 7: 15, 15: 30, 30: 7 } as Record<number, number>)[Number(settings[keyName] ?? 30)]
                        : keyName === "automatic_refinement"
                            ? settings[keyName] === false
                            : keyName === "automatic_forgetting"
                                ? ({ off: "idle", idle: "capacity", capacity: "idle_capacity", idle_capacity: "off" } as Record<string, string>)[String(settings[keyName] ?? "off")]
                                : settings[keyName];
                if (keyName) send({ type: "memory_panel_action", action: "setting", entry_id: keyName, value: nextValue });
            } else if (memoryPanel.view === "entries" && selected) {
                send({ type: "memory_panel_action", action: "detail", target: memoryPanel.target ?? undefined, entry_id: selected.entry_id });
            } else if (memoryPanel.view === "revisions" && selected && !memoryPanel.readOnly) {
                send({
                    type: "memory_panel_action",
                    action: "restore_revision",
                    target: memoryPanel.target ?? undefined,
                    entry_id: String(memoryPanel.settings?.entry_id ?? ""),
                    value: Number(selected.entry_id),
                });
            }
        } else if (inputKey.toLowerCase() === "f" && selected && !memoryPanel.readOnly && memoryPanel.target !== "dump") {
            send({ type: "memory_panel_action", action: "forget", target: memoryPanel.target ?? undefined, entry_id: selected.entry_id });
        } else if (inputKey.toLowerCase() === "r" && selected && !memoryPanel.readOnly && memoryPanel.target === "dump") {
            send({ type: "memory_panel_action", action: "recall", target: "dump", entry_id: selected.entry_id });
        } else if (inputKey === "/" && memoryPanel.view === "entries") {
            setMemoryEditor({ mode: "search", value: memorySearchQuery });
        } else if (inputKey.toLowerCase() === "a" && memoryPanel.view === "entries" && memoryPanel.target !== "dump" && !memoryPanel.readOnly) {
            setMemoryEditor({ mode: "add", value: "" });
        } else if (inputKey.toLowerCase() === "e" && selected && memoryPanel.target !== "dump" && !memoryPanel.readOnly) {
            setMemoryEditor({ mode: "edit", value: selected.content });
        } else if (inputKey.toLowerCase() === "m" && selected && memoryPanel.target !== "dump" && !memoryPanel.readOnly) {
            const target = memoryPanel.target === "user" ? "memory" : "user";
            send({ type: "memory_panel_action", action: "move", target, entry_id: selected.entry_id });
        } else if (inputKey.toLowerCase() === "y" && selected?.review_pending && !memoryPanel.readOnly) {
            send({ type: "memory_panel_action", action: "review_accept", target: memoryPanel.target ?? undefined, entry_id: selected.entry_id });
        } else if (inputKey.toLowerCase() === "n" && selected?.review_pending && !memoryPanel.readOnly) {
            send({ type: "memory_panel_action", action: "review_reject", target: memoryPanel.target ?? undefined, entry_id: selected.entry_id });
        } else if (inputKey.toLowerCase() === "v" && selected && memoryPanel.view === "detail" && !memoryPanel.readOnly) {
            send({ type: "memory_panel_action", action: "revisions", target: memoryPanel.target ?? undefined, entry_id: selected.entry_id });
        } else if (inputKey.toLowerCase() === "b" && memoryPanel.view === "root" && memoryPanel.readOnly && memoryPanel.hint?.includes("rebuild")) {
            send({ type: "memory_panel_action", action: "rebuild" });
        }
    }, { isActive: activeRegion === "memoryPanel" && Boolean(memoryPanel) && rawModeAvailable && !confirm });

    useInput((inputKey, key) => {
        if (!playbackSessionActive || confirm || isSlashMenuActive || languagePanel?.active || isModelPanelActive) return;
        if (key.tab || inputKey === "\t") {
            const nextShellState = reduceShellState(shellStateRef.current, {
                type: "toggle_region",
                spotifyModeEnabled: false,
                providerModeEnabled: providerModeRef.current.enabled,
            });
            if (nextShellState.region !== shellStateRef.current.region) {
                switchRegion(nextShellState.region);
            }
            applyShellAction({ type: "replace", state: nextShellState });
        }
    }, { isActive: rawModeAvailable && playbackSessionActive && !confirm && !isSlashMenuActive && !languagePanel?.active && !isModelPanelActive });

    useInput((_inputKey, key) => {
        if (!key.escape || !agentWorkingTurnId) return;
        const sent = send({
            type: "agent_turn_interrupt",
            turn_id: agentWorkingTurnId,
        });
        if (sent) {
            applyRuntimeAction({ type: "clear_agent_working" });
        }
    }, {
        isActive: rawModeAvailable
            && activeRegion === "chat"
            && agentWorkingTurnId !== null
            && !confirm
            && !isSlashMenuActive
            && !helpPanel
            && !languagePanel?.active
            && !spotifySetup?.active
            && !authSetup?.active
            && !trackPanel,
    });

    return (
        <>
            <CommittedTranscript
                records={transcript.records}
            />
            <Box
                flexDirection="column"
                width={terminalSize.columns ?? "100%"}
                height={activeRegion === "chat" || activeRegion === "memoryPanel" ? undefined : dynamicSurfaceHeight}
                minHeight={0}
            >
                {showFixedHeader ? (
                    <HeaderFrame
                        authState={authState}
                        cwd={RUNTIME_WORKING_DIRECTORY}
                        sessionId={sessionId}
                        variant={headerVariant}
                        language={language}
                    />
                ) : null}
                {isLoginScreenActive ? (
                    <LoginScreen
                        authSetup={authSetup}
                        selectedIndex={loginSelectionIndex}
                        apiKeyInput={loginApiKeyInput}
                        setApiKeyInput={setLoginApiKeyInput}
                        onApiKeySubmit={submitLoginApiKey}
                        language={language}
                    />
                ) : (
                    <DynamicShell
                        input={input}
                        setInput={updateInput}
                        onSubmit={submitInput}
                        inputPlaceholder={inputPlaceholder}
                        inputMask={inputMask}
                        inputFocus={(!confirm || Boolean(selectedConfirmInput)) && rawModeAvailable && !isExiting && !helpPanel && !languagePanel?.active && !isModelPanelActive && !recommendInputLocked}
                        inputRevision={inputRevision}
                        player={player}
                        coverUrl={coverUrl}
                        coverPattern={coverPattern}
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
                        modelPanelIndex={loginSelectionIndex}
                        trackPanel={trackPanel}
                        trackPanelIndex={trackPanelIndex}
                        extensionPanel={extensionPanel}
                        extensionPanelIndex={extensionPanelIndex}
                        extensionInputFocused={extensionInputFocused}
                        memoryPanel={memoryPanel}
                        memoryPanelIndex={memoryPanelIndex}
                        memorySearchQuery={memorySearchQuery}
                        memoryEditor={memoryEditor}
                        activeRegion={activeRegion}
                        miniSnapshotRevision={miniSnapshotRevision}
                        miniLayout={miniLayout}
                        spotifyImmersiveLayout={spotifyImmersiveLayout}
                        terminalSpace={terminalSize}
                        agentWorking={agentWorkingTurnId !== null}
                        streamingMessage={streamingMessage}
                        language={language}
                    />
                )}
            </Box>
        </>
    );
};

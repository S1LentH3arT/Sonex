import React, { useState } from 'react';
import { Box, useApp, useInput, useStdin, useStdout } from 'ink';
import { upsertActivity } from './activity.js';
import { completeSlashCommand, hasSlashCommandArguments, matchingSlashCommand, slashCommandSuggestions, spotifyModeSlashCommands } from './commands.js';
import { getVisibleConfirmChoices, resolveConfirmDecisionFromInput, resolveConfirmInputDecision } from './confirm-choice.js';
import { selectedHelpPanelCommand } from './command-panel.js';
import { DEFAULT_CONFIRM_CHOICES, FALLBACK_MODEL_NAME, MAX_CHAT_ITEMS, wsUrl } from './constants.js';
import { DynamicShell, HeaderFrame, isGenericAuthSetup, LoginScreen } from './components.js';
import { clamp, trimList } from './chat-window.js';
import { useSonexSocket } from './hooks.js';
import { applyLanguageToServerEvent, helpCommandsForLanguage, languageLabel, localizeSlashCommands, t } from './i18n.js';
import { LAUNCH_PREPARING_INTERVAL_MS, launchPreparingText, shouldStartLaunchPreparing } from './launch-preparing.js';
import { resolveChatHeaderVariant, resolveMiniPlayerLayout, resolveRegionAfterPlayerEvent, resolveSpotifyImmersiveLayout, toggleShellRegion, type ShellRegion, type TerminalSize } from './layout.js';
import { shouldRefreshMiniSnapshot, usePlaybackProgressWriter, usePlaybackStatusIconWriter } from './mini-progress-writer.js';
import { isLocalPlaybackShortcutSource, playbackCommandForShortcut, playbackShortcutFromInput } from './playback-keymap.js';
import { clearTerminalForLayoutSwitch } from './terminal-clear.js';
import { markQueuedTracks } from './track-panel.js';
import { loadUiLanguage, saveUiLanguage } from './ui-settings.js';
import type { ActivityItem, AuthRuntimeState, AuthSetupState, ChatItem, ConfirmState, CoverPatternEvent, HelpPanelState, LanguagePanelState, PlayerState, SpotifyModeState, SpotifySetupState, TrackPanelState, TrackPanelTrack, TrackSummary, ServerEvent, SlashCommandSuggestion, UiLanguage } from './types.js';

type InkInputKey = {
    ctrl?: boolean;
};

const isTrackPanelQueueShortcut = (inputKey: string, key: InkInputKey): boolean => {
    return Boolean(key.ctrl && (inputKey === "\x01" || inputKey.toLowerCase() === "a"));
};

export const App = () => {
    const { exit } = useApp();
    const { isRawModeSupported } = useStdin();
    const { stdout } = useStdout();
    const rawModeAvailable = Boolean(isRawModeSupported && typeof process.stdin.setRawMode === "function");
    const [language, setLanguage] = useState<UiLanguage>(() => loadUiLanguage());
    const [input, setInput] = useState("");
    const [inputRevision, setInputRevision] = useState(0);
    const [chatItems, setChatItems] = useState<ChatItem[]>([]);
    const [activityItems, setActivityItems] = useState<ActivityItem[]>([]);
    const [queueItems, setQueueItems] = useState<TrackPanelTrack[]>([]);
    const [searchItems, setSearchItems] = useState<TrackSummary[]>([]);
    const [trackPanel, setTrackPanel] = useState<TrackPanelState>(null);
    const [player, setPlayer] = useState<PlayerState>({ name: "-", artist: "-", album: "-", duration_ms: 0, progress_ms: 0, is_playing: false });
    const [statusText, setStatusText] = useState(() => t(loadUiLanguage(), "status.snoozing"));
    const [launchPreparing, setLaunchPreparing] = useState(false);
    const [launchPreparingFrame, setLaunchPreparingFrame] = useState(0);
    const [coverUrl, setCoverUrl] = useState<string | null>(null);
    const [coverPattern, setCoverPattern] = useState<CoverPatternEvent | null>(null);
    const coverUrlRef = React.useRef<string | null>(null);
    const [confirm, setConfirm] = useState<ConfirmState>(null);
    const [confirmIndex, setConfirmIndex] = useState(0); // 0=Yes, 1=No
    const [spotifyMode, setSpotifyMode] = useState<SpotifyModeState>({ enabled: false });
    const [spotifySetup, setSpotifySetup] = useState<SpotifySetupState>(null);
    const [authSetup, setAuthSetup] = useState<AuthSetupState>(null);
    const [authState, setAuthState] = useState<AuthRuntimeState>({
        ready: false,
        provider: "openai",
        model: FALLBACK_MODEL_NAME,
        auth_type: "none",
        credential_source: "pending",
    });
    const [activeRegion, setActiveRegion] = useState<ShellRegion>("chat");
    const [playbackSessionActive, setPlaybackSessionActive] = useState(false);
    const [playbackKeymapEnabled, setPlaybackKeymapEnabled] = useState(true);
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
    const [chatScrollOffset, setChatScrollOffset] = useState(0);
    const [maxChatScrollOffset, setMaxChatScrollOffset] = useState(0);
    const [loginSelectionIndex, setLoginSelectionIndex] = useState(0);
    const [loginApiKeyInput, setLoginApiKeyInput] = useState("");
    const activeRegionRef = React.useRef<ShellRegion>("chat");
    const playbackSessionActiveRef = React.useRef(false);
    const playbackKeymapEnabledRef = React.useRef(true);
    const playerRef = React.useRef<PlayerState>(player);
    const confirmRef = React.useRef<ConfirmState>(null);
    const spotifyModeRef = React.useRef<SpotifyModeState>(spotifyMode);
    const spotifySetupActiveRef = React.useRef(false);
    const authSetupActiveRef = React.useRef(false);
    const slashMenuActiveRef = React.useRef(false);
    const isModelPanelActive = authSetup?.active && authSetup.step === "model";
    const isLoginScreenActive = isGenericAuthSetup(authSetup) && !isModelPanelActive;
    const slashSuggestions = authSetup?.active || spotifySetup?.active || languagePanel?.active
        ? []
        : spotifyMode.enabled
            ? spotifyModeSlashCommands(input, language)
            : slashCommandSuggestions(input, language);
    const slashInput = input.trimStart();
    const isSlashInput = slashInput.startsWith("/");
    const isSlashMenuActive = rawModeAvailable && !confirm && isSlashInput && slashMenuDismissedFor !== input && slashSuggestions.length > 0;
    const selectedSlashCommand = slashSuggestions[Math.min(slashIndex, Math.max(0, slashSuggestions.length - 1))];
    const visibleConfirmChoices = React.useMemo(() => confirm ? getVisibleConfirmChoices(confirm.choices) : [], [confirm]);
    const selectedConfirmChoice = visibleConfirmChoices[Math.min(confirmIndex, Math.max(0, visibleConfirmChoices.length - 1))] ?? null;
    const selectedConfirmInput = selectedConfirmChoice?.input ?? null;
    const miniVisible = activeRegion === "miniPlayer";
    const spotifyImmersiveVisible = activeRegion === "spotifyImmersive";
    const miniLayout = React.useMemo(() => resolveMiniPlayerLayout(terminalSize), [terminalSize.columns, terminalSize.rows]);
    const spotifyImmersiveLayout = React.useMemo(() => resolveSpotifyImmersiveLayout(terminalSize), [terminalSize.columns, terminalSize.rows]);
    const headerVariant = resolveChatHeaderVariant(terminalSize.columns);
    const baseLanguageChoices = React.useMemo<UiLanguage[]>(() => ["en", "zh-CN"], []);
    const languageChoices = React.useMemo<UiLanguage[]>(
        () => [language, ...baseLanguageChoices.filter((choice) => choice !== language)],
        [baseLanguageChoices, language],
    );

    React.useEffect(() => {
        playbackKeymapEnabledRef.current = playbackKeymapEnabled;
    }, [playbackKeymapEnabled]);

    React.useEffect(() => {
        playerRef.current = player;
    }, [player]);

    React.useEffect(() => {
        confirmRef.current = confirm;
    }, [confirm]);

    React.useEffect(() => {
        spotifyModeRef.current = spotifyMode;
    }, [spotifyMode]);

    React.useEffect(() => {
        spotifySetupActiveRef.current = Boolean(spotifySetup?.active);
    }, [spotifySetup?.active]);

    React.useEffect(() => {
        authSetupActiveRef.current = Boolean(authSetup?.active);
    }, [authSetup?.active]);

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
                setTerminalSize(nextSize);
                if (activeRegionRef.current === "miniPlayer" && shouldRefreshMiniSnapshot("resize")) {
                    clearTerminalForLayoutSwitch(stdout);
                    setMiniSnapshotRevision((prev) => prev + 1);
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
    }, [stdout]);

    React.useEffect(() => {
        setChatScrollOffset((prev) => clamp(prev, 0, maxChatScrollOffset));
    }, [maxChatScrollOffset]);

    const scrollChat = React.useCallback((delta: number) => {
        setChatScrollOffset((prev) => clamp(prev + delta, 0, maxChatScrollOffset));
    }, [maxChatScrollOffset]);

    const switchRegion = React.useCallback((nextRegion: ShellRegion) => {
        if (activeRegionRef.current === nextRegion) return;
        clearTerminalForLayoutSwitch(stdout);
        activeRegionRef.current = nextRegion;
        setActiveRegion(nextRegion);
        if (nextRegion === "miniPlayer" && shouldRefreshMiniSnapshot("region")) {
            setMiniSnapshotRevision((prev) => prev + 1);
        }
    }, [stdout]);

    usePlaybackProgressWriter({
        enabled: miniVisible || spotifyImmersiveVisible,
        player,
        position: spotifyImmersiveVisible ? spotifyImmersiveLayout.progressSlot : miniLayout.progressSlot,
        stdout,
    });
    usePlaybackStatusIconWriter({
        enabled: miniVisible,
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
        setLoginSelectionIndex(0);
        setLoginApiKeyInput("");
    }, [authSetup?.step, authSetup?.provider]);

    React.useEffect(() => {
        if (!launchPreparing) return;
        const timer = setInterval(() => {
            setLaunchPreparingFrame((prev) => prev + 1);
        }, LAUNCH_PREPARING_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [launchPreparing]);

    const updateInput = React.useCallback((value: string) => {
        const sanitized = value.replace(/\x1B/g, "");
        setInput(sanitized);
        if (sanitized) {
            setHelpPanel(null);
            setTrackPanel(null);
            setTrackPanelIndex(0);
            setLanguagePanel(null);
        }
        if (sanitized !== slashMenuDismissedFor) {
            setSlashMenuDismissedFor(null);
        }
    }, [slashMenuDismissedFor]);

    const showError = React.useCallback((message: string, detail?: string | null) => {
        const content = detail ? `${message}\n${detail}` : message;
        setChatItems((prev) => trimList([...prev, { role: "agent", content, theme: spotifyModeRef.current.enabled ? "spotify" : undefined }], MAX_CHAT_ITEMS));
        setChatScrollOffset((prev) => prev > 0 ? Math.min(prev + 1, MAX_CHAT_ITEMS - 1) : prev);
    }, []);

    const inputPlaceholder = selectedConfirmInput
        ? selectedConfirmInput.placeholder
        : authSetup?.active && authSetup.prompt
            ? authSetup.prompt
            : spotifySetup?.active && spotifySetup.prompt
                ? spotifySetup.prompt
                : t(language, "input.placeholder");
    const inputMask = authSetup?.active && authSetup.mask
        ? "*"
        : spotifySetup?.active && spotifySetup.mask
            ? "*"
            : undefined;
    const onEvent = React.useCallback((rawEvent: ServerEvent) => {
        const evt = applyLanguageToServerEvent(rawEvent, language);
        switch (evt.type) {
            case "chat":
                setChatItems((prev) => trimList([...prev, { role: evt.role, content: evt.text, theme: evt.theme }], MAX_CHAT_ITEMS));
                setChatScrollOffset((prev) => prev > 0 ? Math.min(prev + 1, MAX_CHAT_ITEMS - 1) : prev);
                break;
            case "activity":
                setActivityItems((prev) => upsertActivity(prev, evt));
                if (shouldStartLaunchPreparing(evt)) {
                    setLaunchPreparing(true);
                    setLaunchPreparingFrame(0);
                } else if (evt.status === "success" || evt.status === "error") {
                    setLaunchPreparing(false);
                }
                break;
            case "status":
                setLaunchPreparing(rawEvent.type === "status" && rawEvent.active !== false && rawEvent.message === "Launch preparing...");
                setStatusText(evt.message);
                break;
            case "queue":
                setQueueItems(evt.tracks);
                setTrackPanel((current) => current ? { ...current, tracks: markQueuedTracks(current.panel === "queue" ? evt.tracks : current.tracks, evt.tracks) } : current);
                break;
            case "track_panel":
                setLaunchPreparing(false);
                switchRegion("chat");
                setTrackPanelIndex(0);
                setTrackPanel({
                    panel: evt.panel,
                    title: evt.title,
                    hint: evt.hint,
                    tracks: markQueuedTracks(evt.tracks, queueItems),
                });
                setStatusText(evt.title);
                break;
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
                setLaunchPreparing(false);
                setPlayer(evt.state);
                const transition = resolveRegionAfterPlayerEvent({
                    currentRegion: activeRegionRef.current,
                    wasSessionActive: playbackSessionActiveRef.current,
                    player: evt.state,
                    spotifyModeEnabled: spotifyModeRef.current.enabled,
                });
                playbackSessionActiveRef.current = transition.sessionActive;
                setPlaybackSessionActive(transition.sessionActive);
                switchRegion(transition.region);
                break;
            case "spotify_mode":
                spotifyModeRef.current = { enabled: evt.enabled, device_id: evt.device_id, device_name: evt.device_name };
                setSpotifyMode({ enabled: evt.enabled, device_id: evt.device_id, device_name: evt.device_name });
                if (!evt.enabled && activeRegionRef.current === "spotifyImmersive") {
                    switchRegion("chat");
                }
                break;
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
            case "error":
                showError(evt.message, evt.detail);
                break;
            case "confirm":
                setLaunchPreparing(false);
                setInput("");
                switchRegion("chat");
                setConfirm({
                    id: evt.id,
                    tool_name: evt.tool_name,
                    tool_args: evt.tool_args,
                    message: evt.message || `Confirm ${evt.tool_name}`,
                    choices: evt.choices && evt.choices.length > 0 ? evt.choices : DEFAULT_CONFIRM_CHOICES,
                });
                setConfirmIndex(0);
                break;
            case "spotify_setup":
                setLaunchPreparing(false);
                setHelpPanel(null);
                if (evt.active !== false) {
                    switchRegion("chat");
                }
                setSpotifySetup({
                    step: evt.step,
                    title: evt.title,
                    message: evt.message,
                    prompt: evt.prompt,
                    mask: evt.mask,
                    active: evt.active !== false,
                });
                setStatusText(evt.title);
                break;
            case "auth_setup":
                setLaunchPreparing(false);
                setHelpPanel(null);
                if (evt.active !== false) {
                    switchRegion("chat");
                }
                setAuthSetup({
                    provider: evt.provider,
                    step: evt.step,
                    title: evt.title,
                    message: evt.message,
                    prompt: evt.prompt,
                    mask: evt.mask,
                    active: evt.active !== false,
                    methods: evt.methods,
                    providers: evt.providers,
                    models: evt.models,
                });
                setStatusText(evt.title);
                break;
            case "auth_state":
                const
                    nextAuthState = {
                    ready: evt.ready,
                    provider: evt.provider,
                    model: evt.model,
                    auth_type: evt.auth_type,
                    credential_source: evt.credential_source,
                    reason: evt.reason,
                };
                setAuthState(nextAuthState);
                break;
            case "help_panel":
                setLaunchPreparing(false);
                setHelpPanel({
                    title: evt.title,
                    hint: evt.hint,
                    commands: helpCommandsForLanguage(evt.commands, language),
                });
                setTrackPanel(null);
                setLanguagePanel(null);
                setHelpPanelIndex(0);
                setStatusText(evt.title);
                break;
            case "bye":
                setLaunchPreparing(false);
                setHelpPanel(null);
                setTrackPanel(null);
                setHelpPanelIndex(0);
                setStatusText(evt.message ?? `Session saved to ${evt.path}. Bye.`);
                setTimeout(() => exit(), 80);
                break;
        }
    }, [exit, language, queueItems, showError, switchRegion]);

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
            if (activeRegionRef.current !== "miniPlayer") return;
            if (!playbackSessionActiveRef.current) return;
            if (!playbackKeymapEnabledRef.current) return;
            if (confirmRef.current) return;
            if (spotifySetupActiveRef.current) return;
            if (authSetupActiveRef.current) return;
            if (slashMenuActiveRef.current) return;
            if (!isLocalPlaybackShortcutSource(playerRef.current)) return;

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
        setChatScrollOffset(0);
        setSlashMenuDismissedFor(null);
        setHelpPanel(null);
        setTrackPanel(null);
        setTrackPanelIndex(0);
        setLanguagePanel(null);
        setHelpPanelIndex(0);
        setStatusText(t(language, "status.saving"));
        setActivityItems((prev) => upsertActivity(prev, {
            id: "bye_saving",
            kind: "status",
            title: "Saving session",
            detail: "Writing transcript before exit.",
            status: "pending",
            timestamp: Date.now(),
        }));

        const sent = send({ type: "bye", messages: chatItems, reason });
        if (!sent) {
            setIsExiting(false);
            showError(
                language === "zh-CN" ? "退出前无法保存会话。" : "Unable to save session before exit.",
                language === "zh-CN" ? "Sonex API 连接未打开。" : "Sonex API connection is not open.",
            );
        }
    }, [chatItems, isExiting, language, send, showError]);

    const appendKeymapMessage = React.useCallback((enabled: boolean) => {
        const mode = enabled ? "enabled" : "pure mode";
        setChatItems((prev) => trimList([...prev, {
            role: "agent",
            content: language === "zh-CN" ? `迷你播放器快捷键已${enabled ? "启用" : "进入纯净模式"}。` : `Mini-player keymap is ${mode}.`,
        }], MAX_CHAT_ITEMS));
        setChatScrollOffset((prev) => prev > 0 ? Math.min(prev + 1, MAX_CHAT_ITEMS - 1) : prev);
    }, [language]);

    const handleKeymapCommand = React.useCallback((args: string) => {
        const value = args.trim().toLowerCase();
        if (!value || value === "toggle") {
            setPlaybackKeymapEnabled((prev) => {
                const next = !prev;
                appendKeymapMessage(next);
                return next;
            });
            return;
        }
        if (value === "on" || value === "enable") {
            setPlaybackKeymapEnabled(true);
            appendKeymapMessage(true);
            return;
        }
        if (value === "off" || value === "disable") {
            setPlaybackKeymapEnabled(false);
            appendKeymapMessage(false);
            return;
        }
        if (value === "status") {
            appendKeymapMessage(playbackKeymapEnabledRef.current);
            return;
        }
        setChatItems((prev) => trimList([...prev, {
            role: "agent",
            content: t(language, "keymap.usage"),
        }], MAX_CHAT_ITEMS));
    }, [appendKeymapMessage, language]);

    const loginChoices = authSetup?.step === "provider"
        ? authSetup.providers ?? []
        : authSetup?.step === "method"
            ? authSetup.methods ?? []
            : authSetup?.step === "model"
                ? authSetup.models ?? []
                : [];
    const displayStatusText = launchPreparing ? launchPreparingText(launchPreparingFrame, language) : statusText;

    const openLanguagePanel = React.useCallback(() => {
        setInput("");
        setSlashMenuDismissedFor(null);
        setHelpPanel(null);
        setTrackPanel(null);
        setTrackPanelIndex(0);
        setLanguagePanel({ active: true, selected: language });
        setLanguagePanelIndex(0);
        setStatusText(t(language, "language.title"));
    }, [language]);

    const chooseLanguage = React.useCallback((nextLanguage: UiLanguage) => {
        let saveError: string | null = null;
        try {
            saveUiLanguage(nextLanguage);
        } catch {
            saveError = t(nextLanguage, "language.saveError");
        }
        setLanguage(nextLanguage);
        setLanguagePanel(saveError ? { active: true, selected: nextLanguage, saveError } : null);
        setStatusText(t(nextLanguage, "language.saved", { language: languageLabel(nextLanguage) }));
        if (saveError) {
            showError(saveError);
        }
    }, [showError]);

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
        const text = value.trim();
        if (!text) return;

        if (confirm) {
            const inputDecision = resolveConfirmInputDecision(text, selectedConfirmChoice);
            if (inputDecision) {
                setInput("");
                send({
                    type: "confirm_result",
                    id: confirm.id,
                    decision: inputDecision,
                });
                setConfirm(null);
                return;
            }
            const decision = resolveConfirmDecisionFromInput(text, visibleConfirmChoices);
            if (!decision) return;
            setInput("");
            send({ type: "confirm_result", id: confirm.id, decision });
            setConfirm(null);
            return;
        }

        const command = matchingSlashCommand(text);
        const suggestions = slashCommandSuggestions(text);
        if (!authSetup?.active && !spotifySetup?.active && (command?.name === "bye" || command?.name === "quit")) {
            requestSafeExit(command.name);
            return;
        }

        if (!authSetup?.active && !spotifySetup?.active && command?.name === "lang") {
            openLanguagePanel();
            return;
        }

        if (!authSetup?.active && !spotifySetup?.active && command?.name === "keymap") {
            setInput("");
            setSlashMenuDismissedFor(null);
            setHelpPanel(null);
            setTrackPanel(null);
            setTrackPanelIndex(0);
            setLanguagePanel(null);
            setHelpPanelIndex(0);
            handleKeymapCommand(text.slice(text.trimStart().split(/\s+/, 1)[0]?.length ?? 0));
            return;
        }

        if (!authSetup?.active && !spotifySetup?.active && text.startsWith("/") && !command) {
            const first = selectedSlashCommand ?? suggestions[0];
            if (first) {
                applySlashCompletion(first);
                setSlashIndex(0);
            }
            return;
        }

        if (
            !authSetup?.active &&
            !spotifySetup?.active &&
            command?.needsArgument &&
            !hasSlashCommandArguments(text)
        ) {
            applySlashCompletion(command);
            return;
        }

        setInput("");
        setSlashMenuDismissedFor(null);
        if (command?.name !== "help") {
            setHelpPanel(null);
            setHelpPanelIndex(0);
        }
        setLanguagePanel(null);
        if (spotifySetup?.active) {
            send({ type: "setup_input", value: text });
        } else if (authSetup?.active) {
            send({ type: "auth_setup_input", value: text });
        } else {
            send({ type: "user_input", text });
        }
    }, [applySlashCompletion, authSetup?.active, confirm, handleKeymapCommand, openLanguagePanel, requestSafeExit, selectedConfirmChoice, selectedConfirmInput, selectedSlashCommand, send, spotifySetup?.active, visibleConfirmChoices]);

    useInput((inputKey, key) => {
        if (key.ctrl && inputKey === "c") {
            requestSafeExit("ctrl_c");
        }
    }, { isActive: rawModeAvailable });

    useInput((inputKey, key) => {
        if (!isLoginScreenActive || authSetup?.step === "api_key") return;

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

    useInput((inputKey, key) => {
        if (!isModelPanelActive) return;
        const choices = authSetup?.models ?? [];

        if (key.upArrow && choices.length > 0) {
            setLoginSelectionIndex((prev) => (prev - 1 + choices.length) % choices.length);
        } else if (key.downArrow && choices.length > 0) {
            setLoginSelectionIndex((prev) => (prev + 1) % choices.length);
        } else if (key.return && choices.length > 0) {
            const choice = choices[Math.min(loginSelectionIndex, Math.max(0, choices.length - 1))];
            if (choice) {
                send({ type: "auth_setup_input", value: choice.value });
            }
        } else if (key.escape) {
            setAuthSetup(null);
            setLoginSelectionIndex(0);
            send({ type: "auth_setup_input", value: "__cancel__" });
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
        if (!languagePanel?.active) return;

        if (key.upArrow) {
            setLanguagePanelIndex((prev) => (prev - 1 + languageChoices.length) % languageChoices.length);
        } else if (key.downArrow) {
            setLanguagePanelIndex((prev) => (prev + 1) % languageChoices.length);
        } else if (key.return) {
            const selected = languageChoices[Math.min(languagePanelIndex, languageChoices.length - 1)] ?? "en";
            chooseLanguage(selected);
        } else if (key.escape) {
            setLanguagePanel(null);
        }
    }, { isActive: Boolean(languagePanel?.active) && rawModeAvailable });

    useInput((inputKey, key) => {
        if (spotifySetup && spotifySetup.active === false && key.escape) {
            setSpotifySetup(null);
        }
        if (authSetup && authSetup.active === false && key.escape) {
            setAuthSetup(null);
        }
    }, { isActive: rawModeAvailable && (Boolean(spotifySetup && spotifySetup.active === false) || Boolean(authSetup && authSetup.active === false)) });

    useInput((inputKey, key) => {
        if (key.pageUp) {
            scrollChat(5);
        } else if (key.pageDown) {
            scrollChat(-5);
        } else if (input.trim().length === 0 && key.upArrow) {
            scrollChat(1);
        } else if (input.trim().length === 0 && key.downArrow) {
            scrollChat(-1);
        }
    }, { isActive: rawModeAvailable && activeRegion !== "miniPlayer" && activeRegion !== "spotifyImmersive" && !confirm && !helpPanel && !isSlashMenuActive && !isLoginScreenActive && !languagePanel?.active && !isModelPanelActive });

    useInput((inputKey, key) => {
        if (!confirm) return;

        if (key.upArrow) {
            setInput("");
            setConfirmIndex((prev) => Math.max(0, prev - 1));
        } else if (key.downArrow) {
            setInput("");
            setConfirmIndex((prev) => visibleConfirmChoices.length > 0 ? Math.min(visibleConfirmChoices.length - 1, prev + 1) : 0);
        } else if (key.return) {
            if (visibleConfirmChoices.length === 0) return;
            if (selectedConfirmChoice?.input) return;
            send({
                type: "confirm_result",
                id: confirm.id,
                decision: selectedConfirmChoice?.value ?? "allow_once",
            });
            setConfirm(null);
        } else if (key.escape) {
            send({ type: "confirm_result", id: confirm.id, decision: "deny" });
            setConfirm(null);
        }
    }, { isActive: Boolean(confirm) && rawModeAvailable });

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
        if (!trackPanel || confirm || isSlashMenuActive || languagePanel?.active || isModelPanelActive) return;
        const selectedTrackPanelTrack = trackPanel.tracks[Math.min(trackPanelIndex, Math.max(0, trackPanel.tracks.length - 1))] ?? null;
        if (key.escape) {
            setTrackPanel(null);
            setTrackPanelIndex(0);
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
    }, { isActive: Boolean(trackPanel) && rawModeAvailable && !confirm && !isSlashMenuActive && !languagePanel?.active && !isModelPanelActive });

    useInput((inputKey, key) => {
        if (!playbackSessionActive || confirm || isSlashMenuActive || languagePanel?.active || isModelPanelActive) return;

        if (activeRegionRef.current === "spotifyImmersive") {
            if (key.ctrl && inputKey === "c") return;
            switchRegion("chat");
            return;
        }

        if (key.tab || inputKey === "\t") {
            switchRegion(toggleShellRegion(activeRegionRef.current, playbackSessionActiveRef.current, spotifyModeRef.current.enabled));
        }
    }, { isActive: rawModeAvailable && playbackSessionActive && !confirm && !isSlashMenuActive && !languagePanel?.active && !isModelPanelActive });

    return (
        <Box
            flexDirection="column"
            width={terminalSize.columns ?? "100%"}
            height={terminalSize.rows ?? undefined}
            minHeight={0}
        >
            {activeRegion === "chat" ? <HeaderFrame authState={authState} variant={headerVariant} language={language} /> : null}
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
                <Box flexDirection="column" width="100%" flexGrow={1} flexShrink={1} minHeight={0}>
                    <DynamicShell
                        input={input}
                        setInput={updateInput}
                        onSubmit={submitInput}
                        inputPlaceholder={inputPlaceholder}
                        inputMask={inputMask}
                        inputFocus={(!confirm || Boolean(selectedConfirmInput)) && rawModeAvailable && !helpPanel && !languagePanel?.active && !isModelPanelActive}
                        inputRevision={inputRevision}
                        chatItems={chatItems}
                        player={player}
                        statusText={displayStatusText}
                        coverUrl={coverUrl}
                        coverPattern={coverPattern}
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
                        modelPanelIndex={loginSelectionIndex}
                        trackPanel={trackPanel}
                        trackPanelIndex={trackPanelIndex}
                        activeRegion={activeRegion}
                        miniSnapshotRevision={miniSnapshotRevision}
                        miniLayout={miniLayout}
                        spotifyImmersiveLayout={spotifyImmersiveLayout}
                        chatScrollOffset={chatScrollOffset}
                        onMaxChatScrollOffsetChange={setMaxChatScrollOffset}
                        terminalSpace={terminalSize}
                        language={language}
                    />
                </Box>
            )}
        </Box>
    );
};

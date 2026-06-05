import React, {useState} from 'react';
import {Box, useApp, useInput, useStdin, useStdout} from 'ink';
import {buildErrorActivity, upsertActivity} from './activity.js';
import {completeSlashCommand, hasSlashCommandArguments, matchingSlashCommand, slashCommandSuggestions} from './commands.js';
import {resolveConfirmDecisionFromInput, resolveConfirmInputDecision} from './confirm-choice.js';
import {DEFAULT_CONFIRM_CHOICES, FALLBACK_MODEL_NAME, MAX_CHAT_ITEMS, wsUrl} from './constants.js';
import {DynamicShell, isGenericAuthSetup, LoginScreen} from './components.js';
import {clamp, trimList} from './chat-window.js';
import {formatElapsed} from './format.js';
import {useSonexSocket} from './hooks.js';
import {LAUNCH_PREPARING_INTERVAL_MS, launchPreparingText, shouldStartLaunchPreparing} from './launch-preparing.js';
import {canUseFullPlaybackLayout, resolveShellLayout, type SmallPlaybackFocus, type TerminalSize} from './layout.js';
import type {ActivityItem, AuthRuntimeState, AuthSetupState, ChatItem, ConfirmState, CoverPatternEvent, HelpPanelState, LayoutMode, PlayerState, SpotifySetupState, TrackSummary, ServerEvent, SlashCommandSuggestion} from './types.js';

const LOCAL_PLAYBACK_COMMANDS = new Set(["pause", "resume", "stop", "progress", "volume", "player"]);

export const App = () => {
    const {exit} = useApp();
    const {isRawModeSupported} = useStdin();
    const {stdout} = useStdout();
    const rawModeAvailable = Boolean(isRawModeSupported && typeof process.stdin.setRawMode === "function");
    const [input, setInput] = useState("");
    const [inputRevision, setInputRevision] = useState(0);
    const [chatItems, setChatItems] = useState<ChatItem[]>([]);
    const [activityItems, setActivityItems] = useState<ActivityItem[]>([]);
    const [queueItems, setQueueItems] = useState<Array<{
        index: string;
        title: string;
        artist: string;
        duration: string
    }>>([]);
    const [searchItems, setSearchItems] = useState<TrackSummary[]>([]);
    const [player, setPlayer] = useState<PlayerState>({name: "-", artist: "-", album: "-", duration_ms: 0, progress_ms: 0, is_playing: false});
    const [statusText, setStatusText] = useState("Snoozing...");
    const [launchPreparing, setLaunchPreparing] = useState(false);
    const [launchPreparingFrame, setLaunchPreparingFrame] = useState(0);
    const [elapsed, setElapsed] = useState<string | null>(null);
    const [tokens, setTokens] = useState<string | null>(null);
    const [showRunMetrics, setShowRunMetrics] = useState(false);
    const [coverUrl, setCoverUrl] = useState<string | null>(null);
    const [coverPattern, setCoverPattern] = useState<CoverPatternEvent | null>(null);
    const coverUrlRef = React.useRef<string | null>(null);
    const [confirm, setConfirm] = useState<ConfirmState>(null);
    const [confirmIndex, setConfirmIndex] = useState(0); // 0=Yes, 1=No
    const [spotifySetup, setSpotifySetup] = useState<SpotifySetupState>(null);
    const [authSetup, setAuthSetup] = useState<AuthSetupState>(null);
    const [authState, setAuthState] = useState<AuthRuntimeState>({
        ready: false,
        provider: "openai",
        model: FALLBACK_MODEL_NAME,
        auth_type: "none",
        credential_source: "pending",
    });
    const [layoutMode, setLayoutMode] = useState<LayoutMode>("compact");
    const [manualLayoutOverride, setManualLayoutOverride] = useState(false);
    const [smallPlaybackFocus, setSmallPlaybackFocus] = useState<SmallPlaybackFocus>("player");
    const [layoutPulse, setLayoutPulse] = useState(false);
    const [terminalSize, setTerminalSize] = useState<TerminalSize>({
        columns: stdout.columns ?? null,
        rows: stdout.rows ?? null,
    });
    const [slashIndex, setSlashIndex] = useState(0);
    const [slashMenuDismissedFor, setSlashMenuDismissedFor] = useState<string | null>(null);
    const [isExiting, setIsExiting] = useState(false);
    const [helpPanel, setHelpPanel] = useState<HelpPanelState>(null);
    const [helpPanelIndex, setHelpPanelIndex] = useState(0);
    const [chatScrollOffset, setChatScrollOffset] = useState(0);
    const [maxChatScrollOffset, setMaxChatScrollOffset] = useState(0);
    const [loginSelectionIndex, setLoginSelectionIndex] = useState(0);
    const [loginApiKeyInput, setLoginApiKeyInput] = useState("");
    const isLoginScreenActive = isGenericAuthSetup(authSetup);
    const slashSuggestions = authSetup?.active || spotifySetup?.active ? [] : slashCommandSuggestions(input);
    const slashInput = input.trimStart();
    const isSlashInput = slashInput.startsWith("/");
    const isSlashMenuActive = rawModeAvailable && !confirm && isSlashInput && slashMenuDismissedFor !== input && slashSuggestions.length > 0;
    const selectedSlashCommand = slashSuggestions[Math.min(slashIndex, Math.max(0, slashSuggestions.length - 1))];
    const selectedConfirmChoice = confirm?.choices[Math.min(confirmIndex, Math.max(0, confirm.choices.length - 1))] ?? null;
    const selectedConfirmInput = selectedConfirmChoice?.input ?? null;
    const fullPlaybackLayoutAvailable = canUseFullPlaybackLayout(terminalSize);
    const resolvedLayout = resolveShellLayout({
        ...terminalSize,
        isPlaying: player.is_playing === true,
        preferredLayout: layoutMode,
        smallPlaybackFocus,
    });

    React.useEffect(() => {
        const updateTerminalSize = () => {
            setTerminalSize({
                columns: stdout.columns ?? null,
                rows: stdout.rows ?? null,
            });
        };

        updateTerminalSize();
        stdout.on("resize", updateTerminalSize);
        return () => {
            stdout.off("resize", updateTerminalSize);
        };
    }, [stdout]);

    React.useEffect(() => {
        setChatScrollOffset((prev) => clamp(prev, 0, maxChatScrollOffset));
    }, [maxChatScrollOffset]);

    const scrollChat = React.useCallback((delta: number) => {
        setChatScrollOffset((prev) => clamp(prev + delta, 0, maxChatScrollOffset));
    }, [maxChatScrollOffset]);

    const flashLayoutTransition = React.useCallback(() => {
        setLayoutPulse(true);
        setTimeout(() => setLayoutPulse(false), 180);
    }, []);

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
        }
        if (sanitized !== slashMenuDismissedFor) {
            setSlashMenuDismissedFor(null);
        }
    }, [slashMenuDismissedFor]);

	    const showError = React.useCallback((message: string, detail?: string | null, includeActivity = true) => {
	        if (includeActivity) {
	            setActivityItems((prev) => upsertActivity(prev, buildErrorActivity(message, detail)));
	        }
	        setChatItems((prev) => trimList([...prev, {role: "agent", content: message}], MAX_CHAT_ITEMS));
            setChatScrollOffset((prev) => prev > 0 ? Math.min(prev + 1, MAX_CHAT_ITEMS - 1) : prev);
	        setStatusText(message);
	        setShowRunMetrics(false);
	    }, []);

    const inputPlaceholder = selectedConfirmInput
        ? selectedConfirmInput.placeholder
        : authSetup?.active && authSetup.prompt
            ? authSetup.prompt
            : spotifySetup?.active && spotifySetup.prompt
                ? spotifySetup.prompt
                : "Say something to awake Sonex.";
    const inputMask = authSetup?.active && authSetup.mask
        ? "*"
        : spotifySetup?.active && spotifySetup.mask
            ? "*"
            : undefined;
	    const onEvent = React.useCallback((evt: ServerEvent) => {
	        switch (evt.type) {
            case "chat":
                setChatItems((prev) => trimList([...prev, {role: evt.role, content: evt.text}], MAX_CHAT_ITEMS));
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
                setLaunchPreparing(evt.active !== false && evt.message === "Launch preparing...");
                setStatusText(evt.message);
                if (evt.active === false) {
                    setShowRunMetrics(false);
                    break;
                }
                const hasRunMetrics = typeof evt.elapsed_ms === "number" || typeof evt.tokens === "number";
                setShowRunMetrics(hasRunMetrics);
                if (typeof evt.elapsed_ms === "number") {
                    setElapsed(formatElapsed(evt.elapsed_ms));
                }
                if (typeof evt.tokens === "number") {
                    setTokens(`${evt.tokens} tokens`);
                }
                break;
            case "queue":
                setQueueItems(evt.tracks);
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
                if (evt.state.is_playing) {
                    setSmallPlaybackFocus("player");
                    if (!manualLayoutOverride) {
                        setLayoutMode("full");
                    }
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
	            case "error":
	                showError(evt.message, evt.detail, false);
	                break;
            case "confirm":
                setLaunchPreparing(false);
                setSmallPlaybackFocus("chat");
                setInput("");
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
                setAuthState({
                    ready: evt.ready,
                    provider: evt.provider,
                    model: evt.model,
                    auth_type: evt.auth_type,
                    credential_source: evt.credential_source,
                    reason: evt.reason,
                });
                break;
            case "help_panel":
                setLaunchPreparing(false);
                setHelpPanel({
                    title: evt.title,
                    hint: evt.hint,
                    commands: evt.commands,
                });
                setHelpPanelIndex(0);
                setStatusText(evt.title);
                break;
            case "bye":
                setLaunchPreparing(false);
                setHelpPanel(null);
                setHelpPanelIndex(0);
                setStatusText(evt.message ?? `Session saved to ${evt.path}. Bye.`);
                setTimeout(() => exit(), 80);
                break;
        }
	    }, [exit, manualLayoutOverride, showError]);

	    const {send} = useSonexSocket({
	        url: wsUrl,
	        onEvent,
	        onClientError: (message, detail) => showError(message, detail),
	    });

    const requestSafeExit = React.useCallback((reason: string) => {
        if (isExiting) return;
        setIsExiting(true);
        setInput("");
        setChatScrollOffset(0);
        setSlashMenuDismissedFor(null);
        setHelpPanel(null);
        setHelpPanelIndex(0);
        setStatusText("Saving session...");
        setActivityItems((prev) => upsertActivity(prev, {
            id: "bye_saving",
            kind: "status",
            title: "Saving session",
            detail: "Writing transcript before exit.",
            status: "pending",
            timestamp: Date.now(),
        }));

        const sent = send({type: "bye", messages: chatItems, reason});
        if (!sent) {
            setIsExiting(false);
            showError("Unable to save session before exit.", "Sonex API connection is not open.");
        }
    }, [chatItems, isExiting, send, showError]);

    const loginChoices = authSetup?.step === "provider"
        ? authSetup.providers ?? []
        : authSetup?.step === "method"
            ? authSetup.methods ?? []
            : authSetup?.step === "model"
                ? authSetup.models ?? []
                : [];
    const displayStatusText = launchPreparing ? launchPreparingText(launchPreparingFrame) : statusText;

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
            send({type: "auth_setup_input", value: choice.value});
        }
    }, [authSetup, loginSelectionIndex, send]);

    const submitLoginApiKey = React.useCallback((value: string) => {
        const text = value.trim();
        if (!text) return;
        setLoginApiKeyInput("");
        send({type: "auth_setup_input", value: text});
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
            const decision = resolveConfirmDecisionFromInput(text, confirm.choices);
            if (!decision) return;
            setInput("");
            send({type: "confirm_result", id: confirm.id, decision});
            setConfirm(null);
            return;
        }

        const command = matchingSlashCommand(text);
        const suggestions = slashCommandSuggestions(text);
        if (!authSetup?.active && !spotifySetup?.active && (command?.name === "bye" || command?.name === "quit")) {
            requestSafeExit(command.name);
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
        if (spotifySetup?.active) {
            send({type: "setup_input", value: text});
        } else if (authSetup?.active) {
            send({type: "auth_setup_input", value: text});
        } else {
            send({type: "user_input", text});
        }
        if (resolvedLayout === "miniPlayer" && !LOCAL_PLAYBACK_COMMANDS.has(command?.name ?? "")) {
            setSmallPlaybackFocus("chat");
        }
    }, [applySlashCompletion, authSetup?.active, confirm, requestSafeExit, resolvedLayout, selectedConfirmChoice, selectedConfirmInput, selectedSlashCommand, send, spotifySetup?.active]);

    useInput((inputKey, key) => {
        if (key.ctrl && inputKey === "c") {
            requestSafeExit("ctrl_c");
        }
    }, {isActive: rawModeAvailable});

    useInput((inputKey, key) => {
        if (!isLoginScreenActive || authSetup?.step === "api_key") return;

        if ((authSetup?.step === "provider" || authSetup?.step === "method" || authSetup?.step === "model") && loginChoices.length > 0) {
            if (key.upArrow) {
                setLoginSelectionIndex((prev) => (prev - 1 + loginChoices.length) % loginChoices.length);
            } else if (key.downArrow) {
                setLoginSelectionIndex((prev) => (prev + 1) % loginChoices.length);
            } else if (key.return) {
                submitLoginChoice();
            }
        }
    }, {isActive: rawModeAvailable && isLoginScreenActive});

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
    }, {isActive: isSlashMenuActive});

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
    }, {isActive: rawModeAvailable && !confirm && !isSlashMenuActive && !isLoginScreenActive});

    useInput((inputKey, key) => {
        if (!confirm) return;

        if (key.upArrow) {
            setInput("");
            setConfirmIndex((prev) => Math.max(0, prev - 1));
        } else if (key.downArrow) {
            setInput("");
            setConfirmIndex((prev) => Math.min(confirm.choices.length - 1, prev + 1));
        } else if (key.return) {
            if (confirm.choices[confirmIndex]?.input) return;
            send({
                type: "confirm_result",
                id: confirm.id,
                decision: confirm.choices[confirmIndex]?.value ?? "allow_once",
            });
            setConfirm(null);
        } else if (key.escape) {
            send({type: "confirm_result", id: confirm.id, decision: "deny"});
            setConfirm(null);
        }
    }, {isActive: Boolean(confirm) && rawModeAvailable});

    useInput((inputKey, key) => {
        if (!helpPanel || confirm || isSlashMenuActive) return;

        if (key.upArrow && helpPanel.commands.length > 0) {
            setHelpPanelIndex((prev) => (prev - 1 + helpPanel.commands.length) % helpPanel.commands.length);
        } else if (key.downArrow && helpPanel.commands.length > 0) {
            setHelpPanelIndex((prev) => (prev + 1) % helpPanel.commands.length);
        } else if (key.escape) {
            setHelpPanel(null);
            setHelpPanelIndex(0);
        }
    }, {isActive: Boolean(helpPanel) && rawModeAvailable && !confirm && !isSlashMenuActive});

    useInput((inputKey, key) => {
        if (!player.is_playing || confirm || isSlashMenuActive) return;

        if (key.tab || inputKey === "\t") {
            setManualLayoutOverride(true);
            if (!fullPlaybackLayoutAvailable) {
                setLayoutMode("full");
                setSmallPlaybackFocus((prev) => prev === "player" ? "chat" : "player");
            } else {
                setLayoutMode((prev) => {
                    const next = prev === "compact" ? "full" : "compact";
                    setSmallPlaybackFocus(next === "full" ? "player" : "chat");
                    return next;
                });
            }
            flashLayoutTransition();
        }
    }, {isActive: rawModeAvailable && !confirm && !isSlashMenuActive});

    if (isLoginScreenActive) {
        return (
            <LoginScreen
                authSetup={authSetup}
                authState={authState}
                selectedIndex={loginSelectionIndex}
                apiKeyInput={loginApiKeyInput}
                setApiKeyInput={setLoginApiKeyInput}
                onApiKeySubmit={submitLoginApiKey}
            />
        );
    }

    return (
        <Box flexDirection="column" width="100%" height="100%" minHeight={0}>
            <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
                <DynamicShell
                    authState={authState}
                    input={input}
                    setInput={updateInput}
                    onSubmit={submitInput}
                    inputPlaceholder={inputPlaceholder}
                    inputMask={inputMask}
                    inputFocus={(!confirm || Boolean(selectedConfirmInput)) && rawModeAvailable}
                    inputRevision={inputRevision}
                    chatItems={chatItems}
                    queueItems={queueItems}
                    player={player}
                    statusText={displayStatusText}
                    elapsed={elapsed}
                    tokens={tokens}
                    showRunMetrics={showRunMetrics}
                    coverUrl={coverUrl}
                    coverPattern={coverPattern}
                    confirm={confirm}
                    confirmIndex={confirmIndex}
                    spotifySetup={spotifySetup}
                    authSetup={authSetup}
                    slashSuggestions={slashSuggestions}
                    slashIndex={slashIndex}
                    helpPanel={helpPanel}
                    helpPanelIndex={helpPanelIndex}
                    layout={resolvedLayout}
                    layoutPulse={layoutPulse}
                    smallPlaybackFocus={smallPlaybackFocus}
                    chatScrollOffset={chatScrollOffset}
                    onMaxChatScrollOffsetChange={setMaxChatScrollOffset}
                    terminalSpace={{
                        columns: terminalSize.columns ? Math.max(0, terminalSize.columns - 4) : null,
                        rows: terminalSize.rows ? Math.max(0, terminalSize.rows - 8) : null,
                    }}
                />
            </Box>
        </Box>
    );
};

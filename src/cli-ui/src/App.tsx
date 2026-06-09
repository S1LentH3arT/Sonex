import React, { useState } from 'react';
import { Box, Static, useApp, useInput, useStdin, useStdout } from 'ink';
import { buildErrorActivity, upsertActivity } from './activity.js';
import { completeSlashCommand, hasSlashCommandArguments, matchingSlashCommand, slashCommandSuggestions } from './commands.js';
import { resolveConfirmDecisionFromInput, resolveConfirmInputDecision } from './confirm-choice.js';
import { DEFAULT_CONFIRM_CHOICES, FALLBACK_MODEL_NAME, MAX_CHAT_ITEMS, wsUrl } from './constants.js';
import { DynamicShell, HeaderFrame, isGenericAuthSetup, LoginScreen } from './components.js';
import { clamp, trimList } from './chat-window.js';
import { formatElapsed } from './format.js';
import { useSonexSocket } from './hooks.js';
import { LAUNCH_PREPARING_INTERVAL_MS, launchPreparingText, shouldStartLaunchPreparing } from './launch-preparing.js';
import { resolvePlayerEventFocus, resolveShellLayout, shouldReturnToChatAfterSubmit, type ShellLayout, type SmallPlaybackFocus, type TerminalSize } from './layout.js';
import { useMiniProgressWriter } from './mini-progress.js';
import { clearTerminalForLayoutSwitch } from './terminal-clear.js';
import type { ActivityItem, AuthRuntimeState, AuthSetupState, ChatItem, ConfirmState, CoverPatternEvent, HelpPanelState, PlayerState, SpotifySetupState, TrackSummary, ServerEvent, SlashCommandSuggestion } from './types.js';

/**
 * Defines the local playback commands constant.
 *
 * Stores stable configuration or display data consumed by App.tsx.
 */
const LOCAL_PLAYBACK_COMMANDS = new Set(["pause", "resume", "stop", "progress", "volume", "player"]);

/**
 * Describes the banner item type.
 *
 * Documents the shape shared across App.tsx call sites.
 */
type BannerItem = {
    id: string;
    authState: AuthRuntimeState;
};

/**
 * Auth banner signature.
 *
 * Coordinates the auth banner signature operation for the CLI UI runtime.
 *
 * @param state Input value used by the auth banner signature operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function authBannerSignature(state: AuthRuntimeState): string {
    return [
        state.ready ? "ready" : "blocked",
        state.provider,
        state.model,
        state.auth_type,
        state.credential_source,
    ].join(":");
}

/**
 * Should append auth banner.
 *
 * Coordinates the should append auth banner operation for the CLI UI runtime.
 *
 * @param previousSignature Input value used by the should append auth banner operation.
 * @param state Input value used by the should append auth banner operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function shouldAppendAuthBanner(previousSignature: string | null, state: AuthRuntimeState): boolean {
    return previousSignature !== authBannerSignature(state);
}

/**
 * Should render static banner.
 *
 * Coordinates the should render static banner operation for the CLI UI runtime.
 *
 * @param layout Input value used by the should render static banner operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function shouldRenderStaticBanner(layout: ShellLayout): boolean {
    return layout !== "miniPlayer";
}

/**
 * Defines the app function.
 *
 * Implements the app behavior used by App.tsx.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export const App = () => {
    /**
     * Defines the {exit} constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const { exit } = useApp();
    /**
     * Defines the {is raw mode supported} constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const { isRawModeSupported } = useStdin();
    /**
     * Defines the {stdout} constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const { stdout } = useStdout();
    /**
     * Defines the raw mode available constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const rawModeAvailable = Boolean(isRawModeSupported && typeof process.stdin.setRawMode === "function");
    /**
     * Defines the [input, set input] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [input, setInput] = useState("");
    /**
     * Defines the [input revision, set input revision] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [inputRevision, setInputRevision] = useState(0);
    /**
     * Defines the [chat items, set chat items] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [chatItems, setChatItems] = useState<ChatItem[]>([]);
    /**
     * Defines the [activity items, set activity items] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [activityItems, setActivityItems] = useState<ActivityItem[]>([]);
    /**
     * Defines the [queue items, set queue items] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [queueItems, setQueueItems] = useState<Array<{
        index: string;
        title: string;
        artist: string;
        duration: string
    }>>([]);
    /**
     * Defines the [search items, set search items] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [searchItems, setSearchItems] = useState<TrackSummary[]>([]);
    /**
     * Defines the [player, set player] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [player, setPlayer] = useState<PlayerState>({ name: "-", artist: "-", album: "-", duration_ms: 0, progress_ms: 0, is_playing: false });
    /**
     * Defines the [status text, set status text] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [statusText, setStatusText] = useState("Snoozing...");
    /**
     * Defines the [launch preparing, set launch preparing] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [launchPreparing, setLaunchPreparing] = useState(false);
    /**
     * Defines the [launch preparing frame, set launch preparing frame] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [launchPreparingFrame, setLaunchPreparingFrame] = useState(0);
    /**
     * Defines the [elapsed, set elapsed] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [elapsed, setElapsed] = useState<string | null>(null);
    /**
     * Defines the [tokens, set tokens] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [tokens, setTokens] = useState<string | null>(null);
    /**
     * Defines the [show run metrics, set show run metrics] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [showRunMetrics, setShowRunMetrics] = useState(false);
    /**
     * Defines the [cover url, set cover url] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [coverUrl, setCoverUrl] = useState<string | null>(null);
    /**
     * Defines the [cover pattern, set cover pattern] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [coverPattern, setCoverPattern] = useState<CoverPatternEvent | null>(null);
    /**
     * Defines the cover url ref constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const coverUrlRef = React.useRef<string | null>(null);
    /**
     * Defines the [confirm, set confirm] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [confirm, setConfirm] = useState<ConfirmState>(null);
    /**
     * Defines the [confirm index, set confirm index] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [confirmIndex, setConfirmIndex] = useState(0); // 0=Yes, 1=No
    /**
     * Defines the [spotify setup, set spotify setup] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [spotifySetup, setSpotifySetup] = useState<SpotifySetupState>(null);
    /**
     * Defines the [auth setup, set auth setup] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [authSetup, setAuthSetup] = useState<AuthSetupState>(null);
    /**
     * Defines the [auth state, set auth state] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [authState, setAuthState] = useState<AuthRuntimeState>({
        ready: false,
        provider: "openai",
        model: FALLBACK_MODEL_NAME,
        auth_type: "none",
        credential_source: "pending",
    });
    /**
     * Defines the [small playback focus, set small playback focus] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [smallPlaybackFocus, setSmallPlaybackFocus] = useState<SmallPlaybackFocus>("player");
    /**
     * Defines the [layout pulse, set layout pulse] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [layoutPulse, setLayoutPulse] = useState(false);
    /**
     * Defines the [mini snapshot revision, set mini snapshot revision] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [miniSnapshotRevision, setMiniSnapshotRevision] = useState(0);
    /**
     * Defines the [terminal size, set terminal size] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [terminalSize, setTerminalSize] = useState<TerminalSize>({
        columns: stdout.columns ?? null,
        rows: stdout.rows ?? null,
    });
    /**
     * Defines the [slash index, set slash index] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [slashIndex, setSlashIndex] = useState(0);
    /**
     * Defines the [slash menu dismissed for, set slash menu dismissed for] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [slashMenuDismissedFor, setSlashMenuDismissedFor] = useState<string | null>(null);
    /**
     * Defines the [is exiting, set is exiting] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [isExiting, setIsExiting] = useState(false);
    /**
     * Defines the [help panel, set help panel] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [helpPanel, setHelpPanel] = useState<HelpPanelState>(null);
    /**
     * Defines the [help panel index, set help panel index] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [helpPanelIndex, setHelpPanelIndex] = useState(0);
    /**
     * Defines the [chat scroll offset, set chat scroll offset] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [chatScrollOffset, setChatScrollOffset] = useState(0);
    /**
     * Defines the [max chat scroll offset, set max chat scroll offset] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [maxChatScrollOffset, setMaxChatScrollOffset] = useState(0);
    /**
     * Defines the [login selection index, set login selection index] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [loginSelectionIndex, setLoginSelectionIndex] = useState(0);
    /**
     * Defines the [login api key input, set login api key input] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [loginApiKeyInput, setLoginApiKeyInput] = useState("");
    /**
     * Defines the [banner items, set banner items] constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const [bannerItems, setBannerItems] = useState<BannerItem[]>([]);
    /**
     * Defines the last banner signature ref constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const lastBannerSignatureRef = React.useRef<string | null>(null);
    /**
     * Defines the banner sequence ref constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const bannerSequenceRef = React.useRef(0);
    /**
     * Defines the is login screen active constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const isLoginScreenActive = isGenericAuthSetup(authSetup);
    /**
     * Defines the slash suggestions constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const slashSuggestions = authSetup?.active || spotifySetup?.active ? [] : slashCommandSuggestions(input);
    /**
     * Defines the slash input constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const slashInput = input.trimStart();
    /**
     * Defines the is slash input constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const isSlashInput = slashInput.startsWith("/");
    /**
     * Defines the is slash menu active constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const isSlashMenuActive = rawModeAvailable && !confirm && isSlashInput && slashMenuDismissedFor !== input && slashSuggestions.length > 0;
    /**
     * Defines the selected slash command constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const selectedSlashCommand = slashSuggestions[Math.min(slashIndex, Math.max(0, slashSuggestions.length - 1))];
    /**
     * Defines the selected confirm choice constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const selectedConfirmChoice = confirm?.choices[Math.min(confirmIndex, Math.max(0, confirm.choices.length - 1))] ?? null;
    /**
     * Defines the selected confirm input constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const selectedConfirmInput = selectedConfirmChoice?.input ?? null;
    /**
     * Defines the resolved layout constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const resolvedLayout = resolveShellLayout({
        ...terminalSize,
        isPlaying: player.is_playing === true,
        preferredLayout: "compact",
        smallPlaybackFocus,
    });
    /**
     * Defines the mini visible constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const miniVisible = resolvedLayout === "miniPlayer";

    React.useEffect(() => {
        /**
         * Defines the update terminal size function.
         *
         * Implements the update terminal size behavior used by App.tsx.
         * @returns The computed result for the surrounding CLI UI flow.
         */
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

    /**
     * Defines the scroll chat constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const scrollChat = React.useCallback((delta: number) => {
        setChatScrollOffset((prev) => clamp(prev + delta, 0, maxChatScrollOffset));
    }, [maxChatScrollOffset]);

    /**
     * Defines the flash layout transition constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const flashLayoutTransition = React.useCallback(() => {
        setLayoutPulse(true);
        setTimeout(() => setLayoutPulse(false), 180);
    }, []);

    React.useEffect(() => {
        if (miniVisible) {
            setMiniSnapshotRevision((prev) => prev + 1);
        }
    }, [miniVisible]);

    useMiniProgressWriter({
        enabled: miniVisible,
        player,
        terminalSize,
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
        /**
         * Defines the timer constant.
         *
         * Stores stable configuration or display data consumed by App.tsx.
         */
        const timer = setInterval(() => {
            setLaunchPreparingFrame((prev) => prev + 1);
        }, LAUNCH_PREPARING_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [launchPreparing]);

    /**
     * Defines the update input constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const updateInput = React.useCallback((value: string) => {
        /**
         * Defines the sanitized constant.
         *
         * Stores stable configuration or display data consumed by App.tsx.
         */
        const sanitized = value.replace(/\x1B/g, "");
        setInput(sanitized);
        if (sanitized) {
            setHelpPanel(null);
        }
        if (sanitized !== slashMenuDismissedFor) {
            setSlashMenuDismissedFor(null);
        }
    }, [slashMenuDismissedFor]);

    /**
     * Defines the show error constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const showError = React.useCallback((message: string, detail?: string | null, includeActivity = true) => {
        if (includeActivity) {
            setActivityItems((prev) => upsertActivity(prev, buildErrorActivity(message, detail)));
        }
        setChatItems((prev) => trimList([...prev, { role: "agent", content: message }], MAX_CHAT_ITEMS));
        setChatScrollOffset((prev) => prev > 0 ? Math.min(prev + 1, MAX_CHAT_ITEMS - 1) : prev);
        setStatusText(message);
        setShowRunMetrics(false);
    }, []);

    /**
     * Defines the input placeholder constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const inputPlaceholder = selectedConfirmInput
        ? selectedConfirmInput.placeholder
        : authSetup?.active && authSetup.prompt
            ? authSetup.prompt
            : spotifySetup?.active && spotifySetup.prompt
                ? spotifySetup.prompt
                : "Say something to awake Sonex.";
    /**
     * Defines the input mask constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const inputMask = authSetup?.active && authSetup.mask
        ? "*"
        : spotifySetup?.active && spotifySetup.mask
            ? "*"
            : undefined;
    /**
     * Defines the on event constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const onEvent = React.useCallback((evt: ServerEvent) => {
        switch (evt.type) {
            case "chat":
                setChatItems((prev) => trimList([...prev, { role: evt.role, content: evt.text }], MAX_CHAT_ITEMS));
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
                /**
                 * Defines the has run metrics constant.
                 *
                 * Stores stable configuration or display data consumed by App.tsx.
                 */
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
                /**
                 * Defines the first constant.
                 *
                 * Stores stable configuration or display data consumed by App.tsx.
                 */
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
                /**
                 * Defines the was playing constant.
                 *
                 * Stores stable configuration or display data consumed by App.tsx.
                 */
                const wasPlaying = player.is_playing === true;
                setPlayer(evt.state);
                if (evt.state.is_playing) {
                    setSmallPlaybackFocus((currentFocus) => resolvePlayerEventFocus({
                        wasPlaying,
                        isPlaying: evt.state.is_playing === true,
                        currentFocus,
                    }));
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
                /**
                 * Defines the next auth state constant.
                 *
                 * Stores stable configuration or display data consumed by App.tsx.
                 */
                const nextAuthState = {
                    ready: evt.ready,
                    provider: evt.provider,
                    model: evt.model,
                    auth_type: evt.auth_type,
                    credential_source: evt.credential_source,
                    reason: evt.reason,
                };
                setAuthState(nextAuthState);
                if (shouldAppendAuthBanner(lastBannerSignatureRef.current, nextAuthState)) {
                    lastBannerSignatureRef.current = authBannerSignature(nextAuthState);
                    bannerSequenceRef.current += 1;
                    setBannerItems((prev) => [...prev, { id: `auth_${bannerSequenceRef.current}`, authState: nextAuthState }]);
                }
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
    }, [exit, player.is_playing, showError]);

    /**
     * Defines the {send} constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const { send } = useSonexSocket({
        url: wsUrl,
        onEvent,
        onClientError: (message, detail) => showError(message, detail),
    });

    /**
     * Defines the request safe exit constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
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

        /**
         * Defines the sent constant.
         *
         * Stores stable configuration or display data consumed by App.tsx.
         */
        const sent = send({ type: "bye", messages: chatItems, reason });
        if (!sent) {
            setIsExiting(false);
            showError("Unable to save session before exit.", "Sonex API connection is not open.");
        }
    }, [chatItems, isExiting, send, showError]);

    /**
     * Defines the login choices constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const loginChoices = authSetup?.step === "provider"
        ? authSetup.providers ?? []
        : authSetup?.step === "method"
            ? authSetup.methods ?? []
            : authSetup?.step === "model"
                ? authSetup.models ?? []
                : [];
    /**
     * Defines the display status text constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const displayStatusText = launchPreparing ? launchPreparingText(launchPreparingFrame) : statusText;

    /**
     * Defines the submit login choice constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const submitLoginChoice = React.useCallback(() => {
        if (!authSetup?.active) return;
        /**
         * Defines the choices constant.
         *
         * Stores stable configuration or display data consumed by App.tsx.
         */
        const choices = authSetup.step === "provider"
            ? authSetup.providers ?? []
            : authSetup.step === "method"
                ? authSetup.methods ?? []
                : authSetup.step === "model"
                    ? authSetup.models ?? []
                    : [];
        /**
         * Defines the choice constant.
         *
         * Stores stable configuration or display data consumed by App.tsx.
         */
        const choice = choices[Math.min(loginSelectionIndex, Math.max(0, choices.length - 1))];
        if (choice) {
            send({ type: "auth_setup_input", value: choice.value });
        }
    }, [authSetup, loginSelectionIndex, send]);

    /**
     * Defines the submit login api key constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const submitLoginApiKey = React.useCallback((value: string) => {
        /**
         * Defines the text constant.
         *
         * Stores stable configuration or display data consumed by App.tsx.
         */
        const text = value.trim();
        if (!text) return;
        setLoginApiKeyInput("");
        send({ type: "auth_setup_input", value: text });
    }, [send]);

    /**
     * Defines the apply slash completion constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const applySlashCompletion = React.useCallback((command: SlashCommandSuggestion) => {
        setInput(completeSlashCommand(command));
        setInputRevision((prev) => prev + 1);
        setSlashMenuDismissedFor(null);
    }, []);

    /**
     * Defines the submit input constant.
     *
     * Stores stable configuration or display data consumed by App.tsx.
     */
    const submitInput = React.useCallback((value: string) => {
        /**
         * Defines the text constant.
         *
         * Stores stable configuration or display data consumed by App.tsx.
         */
        const text = value.trim();
        if (!text) return;

        if (confirm) {
            /**
             * Defines the input decision constant.
             *
             * Stores stable configuration or display data consumed by App.tsx.
             */
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
            /**
             * Defines the decision constant.
             *
             * Stores stable configuration or display data consumed by App.tsx.
             */
            const decision = resolveConfirmDecisionFromInput(text, confirm.choices);
            if (!decision) return;
            setInput("");
            send({ type: "confirm_result", id: confirm.id, decision });
            setConfirm(null);
            return;
        }

        /**
         * Defines the command constant.
         *
         * Stores stable configuration or display data consumed by App.tsx.
         */
        const command = matchingSlashCommand(text);
        /**
         * Defines the suggestions constant.
         *
         * Stores stable configuration or display data consumed by App.tsx.
         */
        const suggestions = slashCommandSuggestions(text);
        if (!authSetup?.active && !spotifySetup?.active && (command?.name === "bye" || command?.name === "quit")) {
            requestSafeExit(command.name);
            return;
        }

        if (!authSetup?.active && !spotifySetup?.active && text.startsWith("/") && !command) {
            /**
             * Defines the first constant.
             *
             * Stores stable configuration or display data consumed by App.tsx.
             */
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
            send({ type: "setup_input", value: text });
        } else if (authSetup?.active) {
            send({ type: "auth_setup_input", value: text });
        } else {
            send({ type: "user_input", text });
        }
        if (shouldReturnToChatAfterSubmit({ layout: resolvedLayout, commandName: command?.name ?? null }) && !LOCAL_PLAYBACK_COMMANDS.has(command?.name ?? "")) {
            setSmallPlaybackFocus("chat");
        }
    }, [applySlashCompletion, authSetup?.active, confirm, requestSafeExit, resolvedLayout, selectedConfirmChoice, selectedConfirmInput, selectedSlashCommand, send, spotifySetup?.active]);

    useInput((inputKey, key) => {
        if (key.ctrl && inputKey === "c") {
            requestSafeExit("ctrl_c");
        }
    }, { isActive: rawModeAvailable });

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
    }, { isActive: rawModeAvailable && isLoginScreenActive });

    useInput((inputKey, key) => {
        if (!isSlashMenuActive || !selectedSlashCommand) return;

        if (key.upArrow) {
            setSlashIndex((prev) => (prev - 1 + slashSuggestions.length) % slashSuggestions.length);
        } else if (key.downArrow) {
            setSlashIndex((prev) => (prev + 1) % slashSuggestions.length);
        } else if (key.tab || inputKey === "\t") {
            applySlashCompletion(selectedSlashCommand);
        } else if (key.return) {
            /**
             * Defines the command constant.
             *
             * Stores stable configuration or display data consumed by App.tsx.
             */
            const command = matchingSlashCommand(input);
            if (!command || (command.needsArgument && !hasSlashCommandArguments(input))) {
                applySlashCompletion(selectedSlashCommand);
            }
        } else if (key.escape) {
            setSlashMenuDismissedFor(input);
        }
    }, { isActive: isSlashMenuActive });

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
    }, { isActive: rawModeAvailable && !confirm && !isSlashMenuActive && !isLoginScreenActive });

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
            send({ type: "confirm_result", id: confirm.id, decision: "deny" });
            setConfirm(null);
        }
    }, { isActive: Boolean(confirm) && rawModeAvailable });

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
    }, { isActive: Boolean(helpPanel) && rawModeAvailable && !confirm && !isSlashMenuActive });

    useInput((inputKey, key) => {
        if (!player.is_playing || confirm || isSlashMenuActive) return;

        if (key.tab || inputKey === "\t") {
            clearTerminalForLayoutSwitch(stdout);
            setSmallPlaybackFocus((prev) => prev === "player" ? "chat" : "player");
            setMiniSnapshotRevision((prev) => prev + 1);
        }
    }, { isActive: rawModeAvailable && !confirm && !isSlashMenuActive });

    return (
        <>
            {shouldRenderStaticBanner(resolvedLayout) ? (
                <Static items={bannerItems}>
                    {(item) => <HeaderFrame key={item.id} authState={item.authState} />}
                </Static>
            ) : null}
            {isLoginScreenActive ? (
                <LoginScreen
                    authSetup={authSetup}
                    selectedIndex={loginSelectionIndex}
                    apiKeyInput={loginApiKeyInput}
                    setApiKeyInput={setLoginApiKeyInput}
                    onApiKeySubmit={submitLoginApiKey}
                />
            ) : (
                <Box flexDirection="column" width="100%" minHeight={0}>
                    <DynamicShell
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
                        miniSnapshotRevision={miniSnapshotRevision}
                        smallPlaybackFocus={smallPlaybackFocus}
                        chatScrollOffset={chatScrollOffset}
                        onMaxChatScrollOffsetChange={setMaxChatScrollOffset}
                        terminalSpace={{
                            columns: terminalSize.columns ? Math.max(0, terminalSize.columns - 4) : null,
                            rows: terminalSize.rows ? Math.max(0, terminalSize.rows - 8) : null,
                        }}
                    />
                </Box>
            )}
        </>
    );
};

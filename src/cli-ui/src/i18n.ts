import type { ConfirmChoice, HelpCommand, ServerEvent, SlashCommandSuggestion, UiLanguage } from './types.js';

export const OFFICIAL_UI_LANGUAGE: UiLanguage = "en";

type MessageKey =
    | "activity.empty"
    | "api.notRunning.detail"
    | "api.notRunning.message"
    | "auth.oauth.return"
    | "auth.oauth.waiting"
    | "chat.empty"
    | "command.lang.description"
    | "help.empty"
    | "help.hint"
    | "help.title"
    | "input.label"
    | "input.placeholder"
    | "input.recommendPending"
    | "keymap.usage"
    | "language.english"
    | "language.hint"
    | "language.saveError"
    | "language.saved"
    | "language.simplifiedChinese"
    | "language.title"
    | "launch.preparing"
    | "login.continue"
    | "login.warmup"
    | "methods.label"
    | "panel.confirmHidden"
    | "panel.helpHidden"
    | "panel.languageHidden"
    | "panel.modelHidden"
    | "panel.setupHidden"
    | "panel.spotifySetupHidden"
    | "providers.label"
    | "status.saving"
    | "status.snoozing"
    | "tips.placeholder"
    | "trackPanel.playlist"
    | "trackPanel.playlistHidden"
    | "trackPanel.playlistEmpty"
    | "trackPanel.queue"
    | "trackPanel.queueHidden"
    | "trackPanel.queueEmpty";

const messages: Record<UiLanguage, Record<MessageKey, string>> = {
    en: {
        "activity.empty": "Waiting for agent activity.",
        "api.notRunning.detail": "Start with `sonex`, or run `sonex api` before `sonex tui`.",
        "api.notRunning.message": "Sonex API is not running",
        "auth.oauth.return": "Complete the OAuth flow in your browser, then return here.",
        "auth.oauth.waiting": "Waiting for browser authorization...",
        "chat.empty": "No messages yet.",
        "command.lang.description": "Choose the TUI display language.",
        "help.empty": "No matching commands.",
        "help.hint": "Use Up/Down to choose, Esc to close.",
        "help.title": "Sonex commands",
        "input.label": "Input",
        "input.placeholder": "Ask Sonex anything.",
        "input.recommendPending": "Waiting for recommendations...",
        "keymap.usage": "Usage: /keymap [on|off|toggle|status]",
        "language.english": "English",
        "language.hint": "Esc to close without changing.",
        "language.saveError": "Language changed for this session, but the setting was not saved.",
        "language.saved": "Language set to {language}.",
        "language.simplifiedChinese": "简体中文",
        "language.title": "Language",
        "launch.preparing": "Preparing playback",
        "login.continue": "↑/↓ to select · Enter to continue · Esc to close",
        "login.warmup": "Complete setup to continue.",
        "methods.label": "Methods",
        "panel.confirmHidden": "Confirmation panel hidden.",
        "panel.helpHidden": "Help panel hidden.",
        "panel.languageHidden": "Language panel hidden.",
        "panel.modelHidden": "Model selection panel hidden.",
        "panel.setupHidden": "Setup panel hidden.",
        "panel.spotifySetupHidden": "Spotify setup panel hidden.",
        "providers.label": "Providers",
        "status.saving": "Saving session...",
        "status.snoozing": "Idle...",
        "tips.placeholder": "Tip: use /random to play a recent song.",
        "trackPanel.playlist": "Playlist",
        "trackPanel.playlistHidden": "Playlist panel hidden.",
        "trackPanel.playlistEmpty": "Playlist is empty.",
        "trackPanel.queue": "Queue",
        "trackPanel.queueHidden": "Queue panel hidden.",
        "trackPanel.queueEmpty": "Queue is empty.",
    },
    "zh-CN": {
        "activity.empty": "等待代理活动。",
        "api.notRunning.detail": "先运行 `sonex`，或在 `sonex tui` 前运行 `sonex api`。",
        "api.notRunning.message": "Sonex API 未运行",
        "auth.oauth.return": "在浏览器中完成 OAuth 流程，然后回到这里。",
        "auth.oauth.waiting": "等待浏览器授权...",
        "chat.empty": "还没有消息。",
        "command.lang.description": "选择 TUI 显示语言。",
        "help.empty": "没有匹配的命令。",
        "help.hint": "使用上下键选择，Esc 关闭。",
        "help.title": "Sonex 命令",
        "input.label": "输入",
        "input.placeholder": "和 Sonex 说点什么。",
        "input.recommendPending": "等待Sonex推荐中...",
        "keymap.usage": "用法：/keymap [on|off|toggle|status]",
        "language.english": "English",
        "language.hint": "Esc 关闭且不更改。",
        "language.saveError": "语言已在本会话切换，但设置未保存。",
        "language.saved": "语言已设置为 {language}。",
        "language.simplifiedChinese": "简体中文",
        "language.title": "语言",
        "launch.preparing": "启动准备中",
        "login.continue": "↑/↓ to select · Enter to continue · Esc to close",
        "login.warmup": "开始前先完成一个小设置。",
        "methods.label": "方式",
        "panel.confirmHidden": "确认面板已收起。",
        "panel.helpHidden": "帮助面板已收起。",
        "panel.languageHidden": "语言面板已收起。",
        "panel.modelHidden": "模型选择面板已收起。",
        "panel.setupHidden": "配置面板已收起。",
        "panel.spotifySetupHidden": "Spotify 配置面板已收起。",
        "providers.label": "服务",
        "status.saving": "正在保存会话...",
        "status.snoozing": "休眠中...",
        "tips.placeholder": "提示：试试 /random 随机播放。",
        "trackPanel.playlist": "歌单",
        "trackPanel.playlistHidden": "歌单面板已收起。",
        "trackPanel.playlistEmpty": "歌单为空。",
        "trackPanel.queue": "播放队列",
        "trackPanel.queueHidden": "播放队列已收起。",
        "trackPanel.queueEmpty": "播放队列为空。",
    },
};

const shortcutCommandDescriptions: Record<string, Record<UiLanguage, string>> = {
    bye: { en: "save and exit", "zh-CN": "保存会话并退出" },
    connect: { en: "connect a music account", "zh-CN": "连接音乐账号" },
    help: { en: "show commands", "zh-CN": "显示可用的 Sonex 命令" },
    info: { en: "show runtime info", "zh-CN": "显示当前运行信息" },
    keymap: { en: "toggle playback shortcuts", "zh-CN": "切换迷你播放器快捷键" },
    lang: { en: "choose display language", "zh-CN": "选择 TUI 显示语言" },
    logout: { en: "sign out and exit", "zh-CN": "退出当前 LLM 服务登录并关闭" },
    model: { en: "switch active model", "zh-CN": "切换当前模型" },
    player: { en: "detect and set default player", "zh-CN": "检测并设置默认播放器" },
    playlist: { en: "browse or save playlists", "zh-CN": "浏览或保存播放列表" },
    queue: { en: "show playback queue", "zh-CN": "显示播放队列" },
    quit: { en: "save and exit", "zh-CN": "保存会话并退出" },
    random: { en: "play a recent song", "zh-CN": "从最近歌曲中播放" },
    recommend: { en: "recommend songs", "zh-CN": "按偏好的音乐口味推荐歌曲" },
    resume: { en: "resume playback", "zh-CN": "继续当前播放" },
    sandbox: { en: "check Agent Bash sandbox", "zh-CN": "检查 Agent Bash 沙箱" },
    spotify: { en: "toggle Spotify mode", "zh-CN": "进入或退出持久化 Spotify 模式" },
};

const helpCommandDescriptions: Record<string, Record<UiLanguage, string>> = {
    bye: { en: "save the current session and exit safely", "zh-CN": "保存会话并退出" },
    connect: { en: "connect a supported music account", "zh-CN": "连接支持的音乐账号" },
    exit: { en: "save the current session and exit safely", "zh-CN": "保存会话并退出" },
    help: { en: "show available Sonex commands", "zh-CN": "显示可用的 Sonex 命令" },
    info: { en: "show current runtime information", "zh-CN": "显示当前运行信息" },
    keymap: { en: "enable or disable mini-player playback shortcuts", "zh-CN": "切换迷你播放器快捷键" },
    lang: { en: "choose the TUI display language", "zh-CN": "选择 TUI 显示语言" },
    logout: { en: "sign out from the current LLM provider and exit", "zh-CN": "退出当前 LLM 服务登录并关闭" },
    model: { en: "switch the active model for this session", "zh-CN": "切换当前模型" },
    player: { en: "detect available players and set the device default", "zh-CN": "检测可用播放器并设置设备默认值" },
    playlist: { en: "browse playlists or save the current song", "zh-CN": "浏览或保存播放列表" },
    queue: { en: "show the playback queue", "zh-CN": "显示播放队列" },
    random: { en: "play a random song from the recent Sonex queue", "zh-CN": "从最近歌曲中播放" },
    recommend: { en: "recommend songs based on a taste hint", "zh-CN": "按偏好的音乐口味推荐歌曲" },
    resume: { en: "resume current local playback", "zh-CN": "继续当前播放" },
    sandbox: { en: "check or configure the Agent Bash sandbox", "zh-CN": "检查或配置 Agent Bash 沙箱" },
    spotify: { en: "enter or exit persistent Spotify mode", "zh-CN": "进入或退出持久化 Spotify 模式" },
};

const knownText: Record<string, Record<UiLanguage, string>> = {
    "Snoozing...": {
        en: "Idle...",
        "zh-CN": "休眠中...",
    },
    "Launch preparing...": {
        en: "Preparing playback...",
        "zh-CN": "启动准备中...",
    },
    "Sonex commands": {
        en: "Sonex commands",
        "zh-CN": "Sonex 命令",
    },
    "Use Up/Down to choose, Esc to close.": {
        en: "Use Up/Down to choose, Esc to close.",
        "zh-CN": "使用上下键选择，Esc 关闭。",
    },
    "Spotify setup": {
        en: "Spotify setup",
        "zh-CN": "Spotify 设置",
    },
    "Paste your Spotify client ID.": {
        en: "Paste your Spotify client ID.",
        "zh-CN": "粘贴你的 Spotify Client ID。",
    },
    "Spotify client ID": {
        en: "Spotify client ID",
        "zh-CN": "Spotify Client ID",
    },
    "The /keymap command is handled by the TUI for this session.": {
        en: "The /keymap command is handled by the TUI for this session.",
        "zh-CN": "/keymap 命令由本次 TUI 会话处理。",
    },
    "The /lang command is handled by the TUI for this session.": {
        en: "The /lang command is handled by the TUI for this session.",
        "zh-CN": "/lang 命令由本次 TUI 会话处理。",
    },
    "Confirm player launch.": {
        en: "Confirm player launch.",
        "zh-CN": "确认启动播放器。",
    },
    "Allow Sonex to open mpv?": {
        en: "Allow Sonex to open mpv?",
        "zh-CN": "允许 Sonex 打开 mpv 吗？",
    },
};

const playerConfirmChoices: Record<string, Record<UiLanguage, Partial<ConfirmChoice>>> = {
    mpv: {
        en: { label: "mpv", description: "default backend for smooth background playback" },
        "zh-CN": { label: "mpv", description: "默认播放后端，提供更丝滑的播放体验" },
    },
    deny: {
        en: { label: "Cancel" },
        "zh-CN": { label: "取消" },
    },
};

export function t(language: UiLanguage, key: MessageKey, values: Record<string, string> = {}): string {
    let text = messages[language][key] ?? messages.en[key];
    for (const [name, value] of Object.entries(values)) {
        text = text.replaceAll(`{${name}}`, value);
    }
    return text;
}

export function languageLabel(language: UiLanguage): string {
    return language === "zh-CN" ? t(language, "language.simplifiedChinese") : t(language, "language.english");
}

export function localizeSlashCommands(commands: SlashCommandSuggestion[], language: UiLanguage): SlashCommandSuggestion[] {
    return commands.map((command) => ({
        ...command,
        description: shortcutCommandDescriptions[command.name]?.[language] ?? command.description,
    }));
}

export function helpCommandsForLanguage(commands: HelpCommand[], language: UiLanguage): HelpCommand[] {
    return commands.map((command) => ({
        ...command,
        description: helpCommandDescriptions[command.name]?.[language] ?? command.description,
    }));
}

function translateKnown(value: string | null | undefined, language: UiLanguage): string | null | undefined {
    if (value == null) return value;
    return knownText[value]?.[language] ?? value;
}

function localizeConfirmChoice(choice: ConfirmChoice, stage: unknown, language: UiLanguage): ConfirmChoice {
    const value = String(choice.value || "");
    const table = stage === "player_confirm" ? playerConfirmChoices : null;
    const mapped = table?.[value]?.[language];
    if (!mapped) return choice;
    return {
        ...choice,
        ...mapped,
        input: choice.input,
    };
}

export function applyLanguageToServerEvent<T extends ServerEvent>(event: T, language: UiLanguage): T {
    switch (event.type) {
        case "status":
            return { ...event, message: translateKnown(event.message, language) ?? event.message } as T;
        case "activity":
            return {
                ...event,
                title: translateKnown(event.title, language) ?? event.title,
                detail: translateKnown(event.detail, language) ?? event.detail,
            } as T;
        case "spotify_setup":
            return {
                ...event,
                title: translateKnown(event.title, language) ?? event.title,
                message: translateKnown(event.message, language) ?? event.message,
                prompt: translateKnown(event.prompt, language) ?? event.prompt,
            } as T;
        case "auth_setup":
            return {
                ...event,
                title: translateKnown(event.title, language) ?? event.title,
                message: translateKnown(event.message, language) ?? event.message,
                prompt: translateKnown(event.prompt, language) ?? event.prompt,
            } as T;
        case "help_panel":
            return {
                ...event,
                title: translateKnown(event.title, language) ?? event.title,
                hint: translateKnown(event.hint, language) ?? event.hint,
                commands: helpCommandsForLanguage(event.commands, language),
            } as T;
        case "error":
            return {
                ...event,
                message: translateKnown(event.message, language) ?? event.message,
                detail: translateKnown(event.detail, language) ?? event.detail,
            } as T;
        case "confirm":
            return {
                ...event,
                message: translateKnown(event.message, language) ?? event.message,
                choices: event.choices?.map((choice) => localizeConfirmChoice(choice, event.tool_args.stage, language)) ?? event.choices,
            } as T;
        case "bye":
            return {
                ...event,
                message: translateKnown(event.message, language) ?? event.message,
            } as T;
        case "chat":
            return {
                ...event,
                text: knownText[event.text]?.[language] ?? event.text,
            } as T;
        default:
            return event;
    }
}

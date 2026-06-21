import type { ConfirmChoice, HelpCommand, ServerEvent, SlashCommandSuggestion, UiLanguage } from './types.js';

type MessageKey =
    | "activity.empty"
    | "api.notRunning.detail"
    | "api.notRunning.message"
    | "auth.oauth.return"
    | "auth.oauth.waiting"
    | "chat.empty"
    | "chat.hiddenAbove"
    | "chat.hiddenBelow"
    | "command.lang.description"
    | "help.empty"
    | "help.hint"
    | "help.title"
    | "input.label"
    | "input.placeholder"
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
    | "providers.label"
    | "status.saving"
    | "status.snoozing"
    | "tips.placeholder"
    | "trackPanel.playlist"
    | "trackPanel.playlistEmpty"
    | "trackPanel.queue"
    | "trackPanel.queueEmpty";

const messages: Record<UiLanguage, Record<MessageKey, string>> = {
    en: {
        "activity.empty": "Waiting for agent activity.",
        "api.notRunning.detail": "Start with `sonex`, or run `sonex api` before `sonex tui`.",
        "api.notRunning.message": "Sonex API is not running",
        "auth.oauth.return": "Complete the OAuth flow in your browser, then return here.",
        "auth.oauth.waiting": "Waiting for browser authorization...",
        "chat.empty": "No messages yet.",
        "chat.hiddenAbove": "↑ earlier messages",
        "chat.hiddenBelow": "↓ newer messages",
        "command.lang.description": "Choose the TUI display language.",
        "help.empty": "No matching commands.",
        "help.hint": "Use Up/Down to choose, Esc to close.",
        "help.title": "Sonex commands",
        "input.label": "Input",
        "input.placeholder": "Say something to awake Sonex.",
        "keymap.usage": "Usage: /keymap [on|off|toggle|status]",
        "language.english": "English",
        "language.hint": "Esc to close without changing.",
        "language.saveError": "Language changed for this session, but the setting was not saved.",
        "language.saved": "Language set to {language}.",
        "language.simplifiedChinese": "简体中文",
        "language.title": "Language",
        "launch.preparing": "Launch preparing",
        "login.continue": "Use Up/Down to choose, Enter to continue.",
        "login.warmup": "A little warm-up before we get started.",
        "methods.label": "Methods",
        "providers.label": "Providers",
        "status.saving": "Saving session...",
        "status.snoozing": "Snoozing...",
        "tips.placeholder": "Tips: try /random for a free play.",
        "trackPanel.playlist": "Playlist",
        "trackPanel.playlistEmpty": "Playlist is empty.",
        "trackPanel.queue": "Queue",
        "trackPanel.queueEmpty": "Queue is empty.",
    },
    "zh-CN": {
        "activity.empty": "等待代理活动。",
        "api.notRunning.detail": "先运行 `sonex`，或在 `sonex tui` 前运行 `sonex api`。",
        "api.notRunning.message": "Sonex API 未运行",
        "auth.oauth.return": "在浏览器中完成 OAuth 流程，然后回到这里。",
        "auth.oauth.waiting": "等待浏览器授权...",
        "chat.empty": "还没有消息。",
        "chat.hiddenAbove": "↑ 更早的消息",
        "chat.hiddenBelow": "↓ 更新的消息",
        "command.lang.description": "选择 TUI 显示语言。",
        "help.empty": "没有匹配的命令。",
        "help.hint": "使用上下键选择，Esc 关闭。",
        "help.title": "Sonex 命令",
        "input.label": "输入",
        "input.placeholder": "和 Sonex 说点什么。",
        "keymap.usage": "用法：/keymap [on|off|toggle|status]",
        "language.english": "English",
        "language.hint": "Esc 关闭且不更改。",
        "language.saveError": "语言已在本会话切换，但设置未保存。",
        "language.saved": "语言已设置为 {language}。",
        "language.simplifiedChinese": "简体中文",
        "language.title": "语言",
        "launch.preparing": "启动准备中",
        "login.continue": "使用上下键选择，Enter 继续。",
        "login.warmup": "开始前先完成一个小设置。",
        "methods.label": "方式",
        "providers.label": "服务",
        "status.saving": "正在保存会话...",
        "status.snoozing": "休眠中...",
        "tips.placeholder": "提示：试试 /random 随机播放。",
        "trackPanel.playlist": "歌单",
        "trackPanel.playlistEmpty": "歌单为空。",
        "trackPanel.queue": "播放队列",
        "trackPanel.queueEmpty": "播放队列为空。",
    },
};

const commandDescriptions: Record<string, Record<UiLanguage, string>> = {
    bye: { en: "save session and exit", "zh-CN": "保存会话并退出" },
    help: { en: "show available commands", "zh-CN": "显示可用的 Sonex 命令" },
    keymap: { en: "toggle mini-player playback shortcuts", "zh-CN": "切换迷你播放器快捷键" },
    lang: { en: "choose the TUI display language", "zh-CN": "选择 TUI 显示语言" },
    logout: { en: "log out current LLM provider and exit", "zh-CN": "退出当前 LLM 服务登录并关闭" },
    model: { en: "switch active model", "zh-CN": "切换当前模型" },
    player: { en: "choose playback backend from a panel", "zh-CN": "打开播放后端选择面板" },
    playlist: { en: "browse or save playlists", "zh-CN": "浏览或保存播放列表" },
    queue: { en: "show playback queue", "zh-CN": "显示播放队列" },
    quit: { en: "save session and exit", "zh-CN": "保存会话并退出" },
    random: { en: "play from recent songs", "zh-CN": "从最近歌曲中播放" },
    recommend: { en: "recommend songs of preferred music taste", "zh-CN": "按偏好的音乐口味推荐歌曲" },
    resume: { en: "resume current playback", "zh-CN": "继续当前播放" },
    setup: { en: "configure a music provider", "zh-CN": "配置音乐服务" },
    spotify: { en: "enter or exit session-only Spotify mode", "zh-CN": "进入或退出本次会话的 Spotify 模式" },
};

const knownText: Record<string, Record<UiLanguage, string>> = {
    "Snoozing...": {
        en: "Snoozing...",
        "zh-CN": "休眠中...",
    },
    "Launch preparing...": {
        en: "Launch preparing...",
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
    "Sonex wanna open auto local player (mpv default), confirm?": {
        en: "Sonex wanna open auto local player (mpv default), confirm?",
        "zh-CN": "Sonex 想打开 auto 本地播放器（mpv 默认），是否确认？",
    },
    "Sonex wants to open auto local player (mpv default).": {
        en: "Sonex wants to open auto local player (mpv default).",
        "zh-CN": "Sonex 想打开 auto 本地播放器（mpv 默认）。",
    },
    "Confirm player launch.": {
        en: "Confirm player launch.",
        "zh-CN": "确认启动播放器。",
    },
};

const playbackMethodChoices: Record<string, Record<UiLanguage, Partial<ConfirmChoice>>> = {
    spotify_play: {
        en: {
            label: "🎧 Spotify Play",
            description: "require Spotify Premium subscription and desktop/mobile Spotify apps",
        },
        "zh-CN": {
            label: "🎧 Spotify 播放",
            description: "需要 Spotify Premium 订阅，以及桌面或移动端 Spotify app",
        },
    },
    apple_music_play: {
        en: {
            label: "🍎 Apple Music Play",
            description: "require Apple Music Subscription, play through Sonex internal player",
        },
        "zh-CN": {
            label: "🍎 Apple Music 播放",
            description: "需要 Apple Music 订阅并通过 Sonex 内置播放器播放",
        },
    },
    online_play: {
        en: {
            label: "🌐 Sonex online Play",
            description: "setup Jamendo/Audius before your journey",
        },
        "zh-CN": {
            label: "🌐 Sonex 在线播放",
            description: "需要先配置 Jamendo/Audius API Key",
        },
    },
    cancel: {
        en: { label: "Cancel" },
        "zh-CN": { label: "取消" },
    },
};

const playerConfirmChoices: Record<string, Record<UiLanguage, Partial<ConfirmChoice>>> = {
    mpv: {
        en: { label: "🎧 mpv", description: "default playback backend with smooth experience" },
        "zh-CN": { label: "🎧 mpv", description: "默认播放后端，提供更丝滑的播放体验" },
    },
    cvlc: {
        en: { label: "📻 VLC", description: "only choose it as fallback when mpv is not available" },
        "zh-CN": { label: "📻 VLC", description: "备用播放后台，适配性较差，通常不建议选择" },
    },
    deny: {
        en: { label: "🚫 Cancel" },
        "zh-CN": { label: "🚫 取消" },
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
        description: commandDescriptions[command.name]?.[language] ?? command.description,
    }));
}

export function helpCommandsForLanguage(commands: HelpCommand[], language: UiLanguage): HelpCommand[] {
    return commands.map((command) => ({
        ...command,
        description: commandDescriptions[command.name]?.[language] ?? command.description,
    }));
}

function translateKnown(value: string | null | undefined, language: UiLanguage): string | null | undefined {
    if (value == null) return value;
    return knownText[value]?.[language] ?? value;
}

function localizeConfirmChoice(choice: ConfirmChoice, stage: unknown, language: UiLanguage): ConfirmChoice {
    const value = String(choice.value || "");
    const table = stage === "method_choice"
        ? playbackMethodChoices
        : stage === "player_confirm"
            ? playerConfirmChoices
            : null;
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

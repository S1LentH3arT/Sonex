import assert from 'node:assert/strict';

import { SLASH_COMMANDS } from '../src/constants.js';
import {
    applyLanguageToServerEvent,
    helpCommandsForLanguage,
    languageLabel,
    localizeSlashCommands,
    OFFICIAL_UI_LANGUAGE,
    t,
} from '../src/i18n.js';

assert.equal(OFFICIAL_UI_LANGUAGE, "en");
assert.equal(t("en", "status.snoozing"), "Idle...");
assert.equal(t("zh-CN", "status.snoozing"), "休眠中...");
assert.equal(t("zh-CN", "tips.placeholder"), "提示：试试 /random 随机播放。");
assert.equal(t("zh-CN", "input.placeholder"), "和 Sonex 说点什么。");
assert.equal(t("en", "input.recommendPending"), "Waiting for recommendations...");
assert.equal(t("zh-CN", "input.recommendPending"), "等待Sonex推荐中...");
assert.equal(t("en", "panel.confirmHidden"), "Confirmation panel hidden.");
assert.equal(t("zh-CN", "panel.confirmHidden"), "确认面板已收起。");
assert.equal(t("en", "panel.helpHidden"), "Help panel hidden.");
assert.equal(t("zh-CN", "panel.helpHidden"), "帮助面板已收起。");
assert.equal(t("en", "panel.languageHidden"), "Language panel hidden.");
assert.equal(t("zh-CN", "panel.languageHidden"), "语言面板已收起。");
assert.equal(t("en", "panel.modelHidden"), "Model selection panel hidden.");
assert.equal(t("zh-CN", "panel.modelHidden"), "模型选择面板已收起。");
assert.equal(t("en", "panel.setupHidden"), "Setup panel hidden.");
assert.equal(t("zh-CN", "panel.setupHidden"), "配置面板已收起。");
assert.equal(t("en", "panel.spotifySetupHidden"), "Spotify setup panel hidden.");
assert.equal(t("zh-CN", "panel.spotifySetupHidden"), "Spotify 配置面板已收起。");
assert.equal(t("en", "trackPanel.playlistHidden"), "Playlist panel hidden.");
assert.equal(t("en", "trackPanel.queueHidden"), "Queue panel hidden.");
assert.equal(t("zh-CN", "trackPanel.playlistHidden"), "歌单面板已收起。");
assert.equal(t("zh-CN", "trackPanel.queueHidden"), "播放队列已收起。");
assert.equal(languageLabel("zh-CN"), "简体中文");

const zhSlashCommands = localizeSlashCommands(SLASH_COMMANDS, "zh-CN");
const langCommand = zhSlashCommands.find((command) => command.name === "lang");
assert.equal(langCommand?.usage, "/lang");
assert.equal(langCommand?.description, "选择 TUI 显示语言");
const infoCommand = zhSlashCommands.find((command) => command.name === "info");
assert.equal(infoCommand?.usage, "/info");
assert.equal(infoCommand?.description, "显示当前运行信息");

assert.equal(zhSlashCommands.find((command) => command.name === "play"), undefined);
assert.equal(zhSlashCommands.find((command) => command.name === "search"), undefined);

const englishShortHelp = localizeSlashCommands(SLASH_COMMANDS, "en")
    .find((command) => command.name === "help");
assert.equal(englishShortHelp?.description, "show commands");

const helpCommands = helpCommandsForLanguage([
    { name: "help", usage: "/help", description: "Show available Sonex commands." },
    { name: "sandbox", usage: "/sandbox", description: "Check the Agent Bash sandbox." },
], "zh-CN");
assert.equal(helpCommands[0]?.usage, "/help");
assert.equal(helpCommands[0]?.description, "显示可用的 Sonex 命令");
assert.equal(helpCommands[1]?.usage, "/sandbox");
assert.equal(helpCommands[1]?.description, "检查或配置 Agent Bash 沙箱");

const englishLongHelp = helpCommandsForLanguage([
    { name: "help", usage: "/help", description: "placeholder" },
], "en");
assert.equal(englishLongHelp[0]?.description, "show available Sonex commands");

const statusEvent = applyLanguageToServerEvent({
    type: "status",
    phase: "Idle",
    message: "Snoozing...",
    active: false,
}, "zh-CN");
assert.equal(statusEvent.message, "休眠中...");

const setupEvent = applyLanguageToServerEvent({
    type: "spotify_setup",
    step: "client_id",
    title: "Spotify setup",
    message: "Paste your Spotify client ID.",
    prompt: "Spotify client ID",
    active: true,
}, "zh-CN");
assert.equal(setupEvent.title, "Spotify 设置");
assert.equal(setupEvent.message, "粘贴你的 Spotify Client ID。");
assert.equal(setupEvent.prompt, "Spotify Client ID");

const helpEvent = applyLanguageToServerEvent({
    type: "help_panel",
    title: "Sonex commands",
    hint: "Use Up/Down to choose, Esc to close.",
    commands: [
        { name: "lang", usage: "/lang", description: "Choose the TUI display language." },
    ],
}, "zh-CN");
assert.equal(helpEvent.title, "Sonex 命令");
assert.equal(helpEvent.hint, "使用上下键选择，Esc 关闭。");
assert.equal(helpEvent.commands[0]?.description, "选择 TUI 显示语言");

const arbitraryChat = applyLanguageToServerEvent({
    type: "chat",
    role: "agent",
    text: "Snoozing... is a song lyric in this arbitrary AI answer.",
}, "zh-CN");
assert.equal(arbitraryChat.text, "Snoozing... is a song lyric in this arbitrary AI answer.");

const knownChat = applyLanguageToServerEvent({
    type: "chat",
    role: "agent",
    text: "The /keymap command is handled by the TUI for this session.",
}, "zh-CN");
assert.equal(knownChat.text, "/keymap 命令由本次 TUI 会话处理。");

const playerConfirm = applyLanguageToServerEvent({
    type: "confirm",
    id: "confirm_2",
    tool_name: "play_youtube_song",
    tool_args: {
        query: "song",
        stage: "player_confirm",
        player: "mpv",
        player_label: "mpv",
    },
    message: "Allow Sonex to open mpv?",
    choices: [
        { value: "mpv", label: "🎧 mpv", description: "default controllable backend for smoother background playback." },
        { value: "deny", label: "取消" },
    ],
}, "zh-CN");
assert.equal(playerConfirm.message, "允许 Sonex 打开 mpv 吗？");
assert.equal(playerConfirm.choices?.[0]?.label, "mpv");
assert.equal(playerConfirm.choices?.[0]?.description, "默认播放后端，提供更丝滑的播放体验");
assert.equal(playerConfirm.choices?.[1]?.label, "取消");

const englishPlayerConfirm = applyLanguageToServerEvent({
    type: "confirm",
    id: "confirm_3",
    tool_name: "play_youtube_song",
    tool_args: {
        query: "song",
        stage: "player_confirm",
        player: "mpv",
        player_label: "mpv",
    },
    message: "Allow Sonex to open mpv?",
    choices: [
        { value: "mpv", label: "mpv", description: "Default controllable backend for smoother background playback." },
        { value: "deny", label: "Cancel" },
    ],
}, "en");
assert.equal(englishPlayerConfirm.choices?.[0]?.label, "mpv");
assert.equal(englishPlayerConfirm.choices?.[0]?.description, "default backend for smooth background playback");
assert.equal(englishPlayerConfirm.choices?.[1]?.label, "Cancel");

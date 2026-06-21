import assert from 'node:assert/strict';

import { SLASH_COMMANDS } from '../src/constants.js';
import {
    applyLanguageToServerEvent,
    helpCommandsForLanguage,
    languageLabel,
    localizeSlashCommands,
    t,
} from '../src/i18n.js';

assert.equal(t("en", "status.snoozing"), "Snoozing...");
assert.equal(t("zh-CN", "status.snoozing"), "休眠中...");
assert.equal(t("zh-CN", "tips.placeholder"), "提示：试试 /random 随机播放。");
assert.equal(t("zh-CN", "input.placeholder"), "和 Sonex 说点什么。");
assert.equal(languageLabel("zh-CN"), "简体中文");

const zhSlashCommands = localizeSlashCommands(SLASH_COMMANDS, "zh-CN");
const langCommand = zhSlashCommands.find((command) => command.name === "lang");
assert.equal(langCommand?.usage, "/lang");
assert.equal(langCommand?.description, "选择 TUI 显示语言。");

assert.equal(zhSlashCommands.find((command) => command.name === "play"), undefined);
assert.equal(zhSlashCommands.find((command) => command.name === "search"), undefined);

const helpCommands = helpCommandsForLanguage([
    { name: "help", usage: "/help", description: "Show available Sonex commands." },
    { name: "setup", usage: "/setup [provider]", description: "Configure a music provider." },
], "zh-CN");
assert.equal(helpCommands[0]?.usage, "/help");
assert.equal(helpCommands[0]?.description, "显示可用的 Sonex 命令。");
assert.equal(helpCommands[1]?.usage, "/setup [provider]");
assert.equal(helpCommands[1]?.description, "配置音乐服务。");

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
assert.equal(helpEvent.commands[0]?.description, "选择 TUI 显示语言。");

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

const playbackMethodConfirm = applyLanguageToServerEvent({
    type: "confirm",
    id: "confirm_1",
    tool_name: "playback_choice",
    tool_args: { query: "song", stage: "method_choice" },
    message: "选择播放方式",
    choices: [
        {
            value: "spotify_play",
            label: "🎧 Spotify Play",
            description: "Spotify Premium subscription and desktop/mobile Spotify apps required.",
        },
        {
            value: "apple_music_play",
            label: "🍎 Apple Music Play",
            description: "Apple Music Subscription required. Play through Sonex internal player.",
        },
        {
            value: "online_play",
            label: "🌐 Sonex online Play",
            description: "No subscription required. Play through Sonex internal player.",
        },
        { value: "cancel", label: "Cancel" },
    ],
}, "zh-CN");
assert.equal(playbackMethodConfirm.message, "选择播放方式");
assert.equal(playbackMethodConfirm.choices?.[0]?.label, "🎧 Spotify 播放");
assert.equal(playbackMethodConfirm.choices?.[0]?.description, "需要 Spotify Premium 订阅，以及桌面或移动端 Spotify app。");
assert.equal(playbackMethodConfirm.choices?.[1]?.label, "🍎 Apple Music 播放");
assert.equal(playbackMethodConfirm.choices?.[1]?.description, "需要 Apple Music 订阅。通过 Sonex 内置播放器播放。");
assert.equal(playbackMethodConfirm.choices?.[2]?.label, "🌐 Sonex 在线播放");
assert.equal(playbackMethodConfirm.choices?.[2]?.description, "无需订阅。通过 Sonex 内置播放器播放。");
assert.equal(playbackMethodConfirm.choices?.[3]?.label, "取消");

const playerConfirm = applyLanguageToServerEvent({
    type: "confirm",
    id: "confirm_2",
    tool_name: "play_youtube_song",
    tool_args: {
        query: "song",
        stage: "player_confirm",
        player: "auto",
        player_label: "auto local player (mpv default)",
    },
    message: "Sonex wanna open auto local player (mpv default), confirm?",
    choices: [
        { value: "mpv", label: "🎧 mpv", description: "default controllable backend for smoother background playback." },
        { value: "cvlc", label: "📻 VLC", description: "manual diagnostic backend; use only when you explicitly want VLC." },
        { value: "deny", label: "取消" },
    ],
}, "zh-CN");
assert.equal(playerConfirm.message, "Sonex 想打开 auto 本地播放器（mpv 默认），是否确认？");
assert.equal(playerConfirm.choices?.[0]?.label, "🎧 mpv");
assert.equal(playerConfirm.choices?.[0]?.description, "默认可控后端，用于更流畅的后台播放。");
assert.equal(playerConfirm.choices?.[1]?.label, "📻 VLC");
assert.equal(playerConfirm.choices?.[1]?.description, "手动诊断后端；仅在你明确想使用 VLC 时选择。");

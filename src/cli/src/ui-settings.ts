import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

import { DEFAULT_UI_THEME, isUiThemeId, type UiThemeId } from './ui-theme.js';
import type { UiLanguage } from './types.js';

const SETTINGS_FILE = "ui-settings.json";

export function isUiLanguage(value: unknown): value is UiLanguage {
    return value === "en" || value === "zh-CN";
}

export function sonexHome(): string {
    return process.env.SONEX_HOME || join(homedir(), ".sonex");
}

function settingsPath(): string {
    return join(sonexHome(), SETTINGS_FILE);
}

type UiSettings = {
    language?: unknown;
    theme?: unknown;
};

function readSettings(): UiSettings {
    try {
        const path = settingsPath();
        if (!existsSync(path)) return {};
        const settings = JSON.parse(readFileSync(path, "utf8"));
        return settings && typeof settings === "object" && !Array.isArray(settings)
            ? settings as UiSettings
            : {};
    } catch {
        return {};
    }
}

function writeSettings(update: Partial<{ language: UiLanguage; theme: UiThemeId }>): void {
    const home = sonexHome();
    mkdirSync(home, { recursive: true });
    const current = readSettings();
    writeFileSync(settingsPath(), `${JSON.stringify({ ...current, ...update }, null, 2)}\n`);
}

export function loadUiLanguage(): UiLanguage {
    const settings = readSettings();
    return isUiLanguage(settings.language) ? settings.language : "en";
}

export function saveUiLanguage(language: UiLanguage): void {
    writeSettings({ language });
}

export function loadUiTheme(): UiThemeId {
    const settings = readSettings();
    return isUiThemeId(settings.theme) ? settings.theme : DEFAULT_UI_THEME;
}

export function saveUiTheme(theme: UiThemeId): void {
    writeSettings({ theme });
}

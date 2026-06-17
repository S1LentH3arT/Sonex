import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

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

export function loadUiLanguage(): UiLanguage {
    try {
        const path = settingsPath();
        if (!existsSync(path)) return "en";
        const settings = JSON.parse(readFileSync(path, "utf8")) as { language?: unknown };
        return isUiLanguage(settings.language) ? settings.language : "en";
    } catch {
        return "en";
    }
}

export function saveUiLanguage(language: UiLanguage): void {
    const home = sonexHome();
    mkdirSync(home, { recursive: true });
    writeFileSync(settingsPath(), `${JSON.stringify({ language }, null, 2)}\n`);
}

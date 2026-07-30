import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { loadUiLanguage, saveUiLanguage } from '../src/ui-settings.js';

const withTempHome = (fn: (home: string) => void) => {
    const home = mkdtempSync(join(tmpdir(), 'sonex-ui-settings-'));
    const previous = process.env.SONEX_HOME;
    process.env.SONEX_HOME = home;
    try {
        fn(home);
    } finally {
        if (previous === undefined) {
            delete process.env.SONEX_HOME;
        } else {
            process.env.SONEX_HOME = previous;
        }
        rmSync(home, { recursive: true, force: true });
    }
};

withTempHome((home) => {
    assert.equal(loadUiLanguage(), "en");
    saveUiLanguage("zh-CN");
    assert.equal(loadUiLanguage(), "zh-CN");
    assert.deepEqual(JSON.parse(readFileSync(join(home, "ui-settings.json"), "utf8")), { language: "zh-CN" });
});

withTempHome((home) => {
    writeFileSync(join(home, "ui-settings.json"), JSON.stringify({ language: "fr" }));
    assert.equal(loadUiLanguage(), "en");
});

withTempHome((home) => {
    writeFileSync(join(home, "ui-settings.json"), "{");
    assert.equal(loadUiLanguage(), "en");
});

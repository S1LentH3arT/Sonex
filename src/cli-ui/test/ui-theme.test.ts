import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_UI_THEME, UI_THEME_IDS, resolveUiTheme } from "../src/ui-theme.js";
import { applyUiTheme, BORDER_BLUE, PANEL_BACKGROUND, PANEL_PRIMARY } from "../src/constants.js";

test("built-in themes resolve and invalid values fall back to Sonex", () => {
    assert.deepEqual(UI_THEME_IDS, ["sonex", "nord", "dracula", "catppuccin-mocha", "solarized-dark", "gruvbox-dark"]);
    assert.equal(resolveUiTheme("dracula").panelBackground, "#282a36");
    assert.equal(resolveUiTheme("solarized-dark").accent, "#268bd2");
    assert.equal(resolveUiTheme("invalid" as never).id, DEFAULT_UI_THEME);
});

test("applying a theme updates shared panel tokens", () => {
    applyUiTheme("nord");
    assert.equal(PANEL_BACKGROUND, "#2e3440");
    assert.equal(PANEL_PRIMARY, "#eceff4");
    assert.equal(BORDER_BLUE, "#88c0d0");
    applyUiTheme(DEFAULT_UI_THEME);
});

export type UiThemeId = "sonex" | "nord" | "dracula" | "catppuccin-mocha" | "solarized-dark" | "gruvbox-dark";

export type UiThemeTokens = {
    id: UiThemeId;
    label: string;
    panelBackground: string;
    panelTitle: string;
    primary: string;
    secondary: string;
    accent: string;
    accentSoft: string;
    toolBackground: string;
    codeBackground: string;
    link: string;
    playerSecondary: string;
    playerPaused: string;
};

export const UI_THEMES: Record<UiThemeId, UiThemeTokens> = {
    sonex: {
        id: "sonex",
        label: "Sonex",
        panelBackground: "#48273e",
        panelTitle: "#c8a6ff",
        primary: "#fff4f6",
        secondary: "#808791",
        accent: "#3b82f6",
        accentSoft: "#9fd9ff",
        toolBackground: "#182e66",
        codeBackground: "#252933",
        link: "#9fd9ff",
        playerSecondary: "#bf98a7",
        playerPaused: "#7f5d6b",
    },
    nord: {
        id: "nord",
        label: "Nord",
        panelBackground: "#2e3440",
        panelTitle: "#88c0d0",
        primary: "#eceff4",
        secondary: "#a3b1c2",
        accent: "#88c0d0",
        accentSoft: "#8fbcbb",
        toolBackground: "#3b4252",
        codeBackground: "#3b4252",
        link: "#8fbcbb",
        playerSecondary: "#a3b1c2",
        playerPaused: "#616e82",
    },
    dracula: {
        id: "dracula",
        label: "Dracula",
        panelBackground: "#282a36",
        panelTitle: "#bd93f9",
        primary: "#f8f8f2",
        secondary: "#a6accd",
        accent: "#ff79c6",
        accentSoft: "#8be9fd",
        toolBackground: "#44475a",
        codeBackground: "#44475a",
        link: "#8be9fd",
        playerSecondary: "#a6accd",
        playerPaused: "#6272a4",
    },
    "catppuccin-mocha": {
        id: "catppuccin-mocha",
        label: "Catppuccin Mocha",
        panelBackground: "#1e1e2e",
        panelTitle: "#cba6f7",
        primary: "#cdd6f4",
        secondary: "#9399b2",
        accent: "#89b4fa",
        accentSoft: "#74c7ec",
        toolBackground: "#313244",
        codeBackground: "#313244",
        link: "#74c7ec",
        playerSecondary: "#9399b2",
        playerPaused: "#6c7086",
    },
    "solarized-dark": {
        id: "solarized-dark",
        label: "Solarized Dark",
        panelBackground: "#002b36",
        panelTitle: "#b58900",
        primary: "#fdf6e3",
        secondary: "#839496",
        accent: "#268bd2",
        accentSoft: "#2aa198",
        toolBackground: "#073642",
        codeBackground: "#073642",
        link: "#2aa198",
        playerSecondary: "#93a1a1",
        playerPaused: "#586e75",
    },
    "gruvbox-dark": {
        id: "gruvbox-dark",
        label: "Gruvbox Dark",
        panelBackground: "#282828",
        panelTitle: "#fabd2f",
        primary: "#ebdbb2",
        secondary: "#a89984",
        accent: "#83a598",
        accentSoft: "#8ec07c",
        toolBackground: "#3c3836",
        codeBackground: "#3c3836",
        link: "#8ec07c",
        playerSecondary: "#a89984",
        playerPaused: "#665c54",
    },
};

export const DEFAULT_UI_THEME: UiThemeId = "sonex";
export const UI_THEME_IDS = Object.keys(UI_THEMES) as UiThemeId[];

export function isUiThemeId(value: unknown): value is UiThemeId {
    return typeof value === "string" && value in UI_THEMES;
}

export function resolveUiTheme(value: UiThemeId | null | undefined): UiThemeTokens {
    return UI_THEMES[isUiThemeId(value) ? value : DEFAULT_UI_THEME];
}

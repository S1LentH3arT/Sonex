const ANSI_INVERSE_ON = "\u001B[7m";
const ANSI_INVERSE_OFF = "\u001B[27m";

export const INPUT_CURSOR_BLINK_INTERVAL_MS = 500;

export const hideInputCursor = (output: string): string => (
    output
        .replaceAll(ANSI_INVERSE_ON, "")
        .replaceAll(ANSI_INVERSE_OFF, "")
);

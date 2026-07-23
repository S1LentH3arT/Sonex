const ANSI_INVERSE_ON = "\u001B[7m";
const ANSI_INVERSE_OFF = "\u001B[27m";

export const hideInputCursor = (output: string): string => (
    output
        .replaceAll(ANSI_INVERSE_ON, "")
        .replaceAll(ANSI_INVERSE_OFF, "")
);

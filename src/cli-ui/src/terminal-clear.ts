export type TerminalWriter = {
    write(chunk: string): unknown;
};

const CLEAR_SCREEN_AND_HOME = '\u001B[2J\u001B[H';

export function clearTerminalForLayoutSwitch(stdout: TerminalWriter): void {
    stdout.write(CLEAR_SCREEN_AND_HOME);
}

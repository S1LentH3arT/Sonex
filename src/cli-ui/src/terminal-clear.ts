export type TerminalWriter = {
    write(chunk: string): unknown;
};

const CLEAR_SCREEN_AND_HOME = '\u001B[2J\u001B[H';

/**
 * Coordinates the clear terminal for layout switch operation for the CLI UI runtime.
 *
 * @param stdout Input value used by the clear terminal for layout switch operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function clearTerminalForLayoutSwitch(stdout: TerminalWriter): void {
    stdout.write(CLEAR_SCREEN_AND_HOME);
}

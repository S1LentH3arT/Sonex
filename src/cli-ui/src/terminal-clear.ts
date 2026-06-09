/**
 * Describes the terminal writer type.
 *
 * Documents the shape shared across terminal-clear.ts call sites.
 */
export type TerminalWriter = {
    write(chunk: string): unknown;
};

/**
 * Defines the clear screen and home constant.
 *
 * Stores stable configuration or display data consumed by terminal-clear.ts.
 */
const CLEAR_SCREEN_AND_HOME = '\u001B[2J\u001B[H';

/**
 * Clear terminal for layout switch.
 *
 * Coordinates the clear terminal for layout switch operation for the CLI UI runtime.
 *
 * @param stdout Input value used by the clear terminal for layout switch operation.
 * @returns The computed result for the surrounding CLI UI flow.
 */
export function clearTerminalForLayoutSwitch(stdout: TerminalWriter): void {
    stdout.write(CLEAR_SCREEN_AND_HOME);
}

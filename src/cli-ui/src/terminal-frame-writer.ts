export const APP_CLEAR_SCREEN = '\u001B[2J\u001B[H';
export const INK_CLEAR_SCREEN = '\u001B[2J\u001B[3J\u001B[H';

const SAVE_CURSOR = '\u001B7';
const RESTORE_CURSOR = '\u001B8';
const ERASE_LINE = '\u001B[2K';
const TERMINAL_CONTROL_SEQUENCE =
    /\u001B(?:\][^\u0007]*(?:\u0007|\u001B\\)|\[[0-?]*[ -/]*[@-~]|[()][0-2A-Z]|[=>78])/g;

export type TerminalDimensions = {
    columns?: number;
    rows?: number;
};

export type IncrementalStdout = NodeJS.WriteStream & {
    reset: () => void;
};

const sameDimensions = (
    left: TerminalDimensions | null,
    right: TerminalDimensions,
): boolean => (
    left?.columns === right.columns && left?.rows === right.rows
);

const changedRowsOutput = (previousRows: string[], nextRows: string[]): string => {
    let output = "";

    for (let index = 0; index < nextRows.length; index += 1) {
        if (previousRows[index] === nextRows[index]) continue;
        output += `\u001B[${index + 1};1H${ERASE_LINE}${nextRows[index]}`;
    }

    return output ? `${SAVE_CURSOR}${output}${RESTORE_CURSOR}` : "";
};

/**
 * Converts Ink's repeated full-screen frames into row-level terminal updates.
 *
 * Ink clears the entire terminal whenever rendered output fills its height.
 * Sonex intentionally fills the terminal so its input dock remains anchored at
 * the bottom, which otherwise turns every cursor blink into a full repaint.
 */
export class IncrementalTerminalFrameWriter {
    private previousRows: string[] | null = null;
    private previousDimensions: TerminalDimensions | null = null;

    constructor(private readonly getDimensions: () => TerminalDimensions) {}

    transform(chunk: string): string | null {
        if (chunk.startsWith(APP_CLEAR_SCREEN)) {
            this.reset();
            return chunk;
        }

        if (!chunk.startsWith(INK_CLEAR_SCREEN)) {
            return chunk;
        }

        const frame = chunk.slice(INK_CLEAR_SCREEN.length);
        if (!frame) {
            this.reset();
            return chunk;
        }

        const nextRows = frame.split("\n");
        const nextDimensions = this.getDimensions();
        const previousRows = this.previousRows;
        const canUpdateIncrementally = (
            previousRows !== null
            && previousRows.length === nextRows.length
            && sameDimensions(this.previousDimensions, nextDimensions)
        );

        if (!canUpdateIncrementally) {
            this.previousRows = nextRows;
            this.previousDimensions = nextDimensions;
            return chunk;
        }

        const output = changedRowsOutput(previousRows, nextRows);
        this.previousRows = nextRows;
        this.previousDimensions = nextDimensions;
        return output || null;
    }

    reset(): void {
        this.previousRows = null;
        this.previousDimensions = null;
    }
}

const completeSuppressedWrite = (args: unknown[]): void => {
    const callback = args.at(-1);
    if (typeof callback === "function") {
        queueMicrotask(() => callback());
    }
};

export const stripTerminalControlSequences = (value: string): string => (
    value.replace(TERMINAL_CONTROL_SEQUENCE, "")
);

/**
 * Wraps stdout while preserving its width, events, and direct-write behavior.
 *
 * Ink treats any frame at least as tall as `stdout.rows` as a full-screen app
 * and clears both the visible buffer and scrollback. The renderer-facing proxy
 * intentionally hides `rows`; App receives the real stream separately for
 * layout, resize handling, and direct alternate-screen writers.
 */
export const createIncrementalStdout = (stdout: NodeJS.WriteStream): IncrementalStdout => {
    const frameWriter = new IncrementalTerminalFrameWriter(() => ({
        columns: stdout.columns,
        rows: stdout.rows,
    }));
    const writeThrough = stdout.write.bind(stdout) as (...args: any[]) => boolean;
    const incrementalWrite = ((chunk: string | Uint8Array, ...args: unknown[]): boolean => {
        if (typeof chunk !== "string") {
            return writeThrough(chunk, ...args);
        }

        const safeChunk = stdout.isTTY === true
            ? chunk
            : stripTerminalControlSequences(chunk);
        const output = frameWriter.transform(safeChunk);
        if (output === null) {
            completeSuppressedWrite(args);
            return true;
        }

        return writeThrough(output, ...args);
    }) as NodeJS.WriteStream["write"];

    return new Proxy(stdout, {
        get(target, property) {
            if (property === "write") return incrementalWrite;
            if (property === "reset") return () => frameWriter.reset();
            if (property === "rows") return undefined;
            const value = Reflect.get(target, property, target);
            return typeof value === "function" ? value.bind(target) : value;
        },
    }) as IncrementalStdout;
};

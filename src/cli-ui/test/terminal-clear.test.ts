import assert from 'node:assert/strict';

import { clearTerminalForLayoutSwitch } from '../src/terminal-clear.js';

/**
 * Defines the writes constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/terminal-clear.test.ts.
 */
const writes: string[] = [];
/**
 * Defines the stdout constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/terminal-clear.test.ts.
 */
const stdout = {
    write(chunk: string) {
        writes.push(chunk);
        return true;
    },
};

clearTerminalForLayoutSwitch(stdout);

assert.deepEqual(writes, ['\u001B[2J\u001B[H']);

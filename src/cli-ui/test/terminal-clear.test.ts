import assert from 'node:assert/strict';

import {clearTerminalForLayoutSwitch} from '../src/terminal-clear.js';

const writes: string[] = [];
const stdout = {
    write(chunk: string) {
        writes.push(chunk);
        return true;
    },
};

clearTerminalForLayoutSwitch(stdout);

assert.deepEqual(writes, ['\u001B[2J\u001B[H']);

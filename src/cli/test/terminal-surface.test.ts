import assert from 'node:assert/strict';
import test from 'node:test';

import {
    ALT_SCREEN_CLEAR,
    ALT_SCREEN_ENTER,
    ALT_SCREEN_LEAVE,
    CURSOR_SHOW,
    MOUSE_TRACKING_DISABLE,
    TerminalSurfaceController,
} from '../src/terminal-surface.js';

const harness = (isTTY = true) => {
    const operations: string[] = [];
    const controller = new TerminalSurfaceController({
        isTTY,
        write: (value) => {
            operations.push(`write:${value}`);
        },
        resetFrame: () => {
            operations.push('reset');
        },
    });
    controller.attachRendererClear(() => {
        operations.push('clear');
    });
    return { controller, operations };
};

test('enters, refreshes, and leaves alternate screen in atomic order', () => {
    const { controller, operations } = harness();
    controller.prepare();
    controller.transition('alternate', () => operations.push('commit:mini'));
    controller.transition('alternate', () => operations.push('commit:track'));
    controller.transition('main', () => operations.push('commit:chat'));

    assert.deepEqual(operations, [
        `write:${MOUSE_TRACKING_DISABLE}`,
        'clear',
        'reset',
        `write:${ALT_SCREEN_ENTER}`,
        'commit:mini',
        'clear',
        'reset',
        `write:${ALT_SCREEN_CLEAR}`,
        'commit:track',
        'clear',
        'reset',
        `write:${ALT_SCREEN_LEAVE}`,
        'commit:chat',
    ]);
});

test('dispose is idempotent and restores an active alternate screen', () => {
    const { controller, operations } = harness();
    controller.transition('alternate', () => operations.push('commit:mini'));
    operations.length = 0;

    controller.dispose();
    controller.dispose();

    assert.deepEqual(operations, [
        'clear',
        'reset',
        `write:${ALT_SCREEN_LEAVE}${MOUSE_TRACKING_DISABLE}${CURSOR_SHOW}`,
    ]);
});

test('a duplicate main transition commits without terminal output', () => {
    const { controller, operations } = harness();

    controller.transition('main', () => operations.push('commit:chat'));

    assert.deepEqual(operations, ['commit:chat']);
});

test('dispose clears the main live tail and blocks later transitions', () => {
    const { controller, operations } = harness();

    controller.dispose();
    controller.transition('alternate', () => operations.push('commit:mini'));

    assert.deepEqual(operations, [
        'clear',
        'reset',
        `write:${MOUSE_TRACKING_DISABLE}${CURSOR_SHOW}`,
    ]);
});

test('non-TTY mode emits no terminal control sequences', () => {
    const { controller, operations } = harness(false);
    controller.prepare();
    controller.transition('alternate', (surface) => operations.push(`commit:mini:${surface}`));
    controller.transition('main', (surface) => operations.push(`commit:chat:${surface}`));
    controller.dispose();

    assert.deepEqual(operations, [
        'commit:mini:main',
        'commit:chat:main',
        'reset',
    ]);
});

test('dispose continues terminal restoration when cleanup steps throw', () => {
    const operations: string[] = [];
    const controller = new TerminalSurfaceController({
        isTTY: true,
        write: (value) => {
            operations.push(`write:${value}`);
            throw new Error('write failed');
        },
        resetFrame: () => {
            operations.push('reset');
            throw new Error('reset failed');
        },
    });
    controller.attachRendererClear(() => {
        operations.push('clear');
        throw new Error('clear failed');
    });

    assert.doesNotThrow(() => controller.dispose());
    assert.deepEqual(operations, [
        'clear',
        'reset',
        `write:${MOUSE_TRACKING_DISABLE}${CURSOR_SHOW}`,
    ]);
});

test('a failed alternate transition restores terminal state before rethrowing', () => {
    const operations: string[] = [];
    let failEnter = true;
    const controller = new TerminalSurfaceController({
        isTTY: true,
        write: (value) => {
            operations.push(`write:${value}`);
            if (value === ALT_SCREEN_ENTER && failEnter) {
                failEnter = false;
                throw new Error('enter failed');
            }
        },
        resetFrame: () => {
            operations.push('reset');
        },
    });
    controller.attachRendererClear(() => {
        operations.push('clear');
    });

    assert.throws(
        () => controller.transition('alternate', () => operations.push('commit:mini')),
        /enter failed/,
    );
    assert.deepEqual(operations, [
        'clear',
        'reset',
        `write:${ALT_SCREEN_ENTER}`,
        'clear',
        'reset',
        `write:${ALT_SCREEN_LEAVE}${MOUSE_TRACKING_DISABLE}${CURSOR_SHOW}`,
    ]);
});

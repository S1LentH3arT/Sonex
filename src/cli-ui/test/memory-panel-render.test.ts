import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';

import type { MemoryPanelState } from '../src/types.js';

const stripAnsi = (value: string): string => value.replaceAll(/\u001b\[[0-9;?]*[A-Za-z]/g, '');

test('renders memory choices in place of the input dock', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { DynamicTail }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const stdout = new PassThrough() as PassThrough & { columns: number; rows: number; isTTY: boolean };
    stdout.columns = 80;
    stdout.rows = 24;
    stdout.isTTY = true;
    const stdin = new PassThrough() as PassThrough & { isTTY: boolean; setRawMode: (enabled: boolean) => void };
    stdin.isTTY = true;
    stdin.setRawMode = () => undefined;
    let output = '';
    stdout.on('data', (chunk) => { output += chunk.toString(); });
    const memoryPanel: NonNullable<MemoryPanelState> = {
        view: 'root',
        title: 'Memory',
        hint: 'Enter to select; Esc to hide',
        readOnly: false,
        entries: [],
    };
    const app = render(React.createElement(DynamicTail, {
        input: '',
        setInput: () => undefined,
        onSubmit: () => undefined,
        inputPlaceholder: 'Ask Sonex anything',
        inputFocus: false,
        inputRevision: 0,
        confirm: null,
        confirmIndex: 0,
        spotifyMode: { enabled: false },
        providerMode: { provider: 'normal', enabled: false },
        spotifySetup: null,
        authSetup: null,
        modelStatus: 'gpt-test',
        slashSuggestions: [],
        slashIndex: 0,
        helpPanel: null,
        helpPanelIndex: 0,
        languagePanel: null,
        languagePanelIndex: 0,
        modelPanelIndex: 0,
        memoryPanel,
        memoryPanelIndex: 0,
        memorySearchQuery: '',
        memoryEditor: null,
        terminalColumns: 80,
        agentWorking: false,
        streamingMessage: null,
        language: 'en',
    }), { stdout, stdin, debug: true, exitOnCtrlC: false });

    await new Promise((resolve) => setImmediate(resolve));
    const plain = stripAnsi(output);
    try {
        assert.match(plain, /view memory entries/);
        assert.match(plain, /reset memory/);
        assert.doesNotMatch(plain, /Ask Sonex anything|gpt-test/);
    } finally {
        app.unmount();
        stdin.destroy();
        stdout.destroy();
    }
});

test('renders reset targets and the requested clear description', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { DynamicTail }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const stdout = new PassThrough() as PassThrough & { columns: number; rows: number; isTTY: boolean };
    stdout.columns = 80;
    stdout.rows = 24;
    stdout.isTTY = true;
    const stdin = new PassThrough() as PassThrough & { isTTY: boolean; setRawMode: (enabled: boolean) => void };
    stdin.isTTY = true;
    stdin.setRawMode = () => undefined;
    let output = '';
    stdout.on('data', (chunk) => { output += chunk.toString(); });
    const memoryPanel: NonNullable<MemoryPanelState> = {
        view: 'format',
        title: 'reset memory',
        hint: 'select the memory to clear',
        readOnly: false,
        entries: [],
    };
    const app = render(React.createElement(DynamicTail, {
        input: '', setInput: () => undefined, onSubmit: () => undefined,
        inputPlaceholder: 'Ask Sonex anything', inputFocus: false, inputRevision: 0,
        confirm: null, confirmIndex: 0,
        spotifyMode: { enabled: false }, providerMode: { provider: 'normal', enabled: false },
        spotifySetup: null, authSetup: null, modelStatus: null,
        slashSuggestions: [], slashIndex: 0, helpPanel: null, helpPanelIndex: 0,
        languagePanel: null, languagePanelIndex: 0, modelPanelIndex: 0,
        memoryPanel, memoryPanelIndex: 0, memorySearchQuery: '', memoryEditor: null,
        terminalColumns: 80, agentWorking: false, streamingMessage: null, language: 'en',
    }), { stdout, stdin, debug: true, exitOnCtrlC: false });

    await new Promise((resolve) => setImmediate(resolve));
    const plain = stripAnsi(output);
    try {
        assert.match(plain, /USER\.md/);
        assert.match(plain, /MEMORY\.md/);
        assert.match(plain, /All memory/);
        assert.match(plain, /select the memory to clear/);
    } finally {
        app.unmount();
        stdin.destroy();
        stdout.destroy();
    }
});

test('renders settings over the input dock with a fixed 48-column label', async () => {
    process.env.FORCE_COLOR = '3';
    const [{ default: React }, { render }, { DynamicTail }] = await Promise.all([
        import('react'),
        import('ink'),
        import('../src/components.js'),
    ]);
    const stdout = new PassThrough() as PassThrough & { columns: number; rows: number; isTTY: boolean };
    stdout.columns = 80;
    stdout.rows = 24;
    stdout.isTTY = true;
    const stdin = new PassThrough() as PassThrough & { isTTY: boolean; setRawMode: (enabled: boolean) => void };
    stdin.isTTY = true;
    stdin.setRawMode = () => undefined;
    let output = '';
    stdout.on('data', (chunk) => { output += chunk.toString(); });
    const memoryPanel: NonNullable<MemoryPanelState> = {
        view: 'settings',
        title: 'Settings · Memory',
        hint: 'Enter to change; Esc to hide',
        readOnly: false,
        entries: [],
        settings: {
            forget_retention_days: 7,
            user_capacity: 'Unlimited',
            memory_capacity: 24,
            automatic_forgetting: 'idle_capacity',
            idle_threshold_days: 30,
            automatic_refinement: true,
            user_refinement_window: 8,
            memory_refinement_window: 12,
        },
    };
    const app = render(React.createElement(DynamicTail, {
        input: '', setInput: () => undefined, onSubmit: () => undefined,
        inputPlaceholder: 'Ask Sonex anything', inputFocus: false, inputRevision: 0,
        confirm: null, confirmIndex: 0,
        spotifyMode: { enabled: false }, providerMode: { provider: 'normal', enabled: false },
        spotifySetup: null, authSetup: null, modelStatus: 'gpt-test',
        slashSuggestions: [], slashIndex: 0, helpPanel: null, helpPanelIndex: 0,
        languagePanel: null, languagePanelIndex: 0, modelPanelIndex: 0,
        memoryPanel, memoryPanelIndex: 0, memorySearchQuery: '', memoryEditor: null,
        terminalColumns: 80, agentWorking: false, streamingMessage: null, language: 'en',
    }), { stdout, stdin, debug: true, exitOnCtrlC: false });

    await new Promise((resolve) => setImmediate(resolve));
    const plain = stripAnsi(output);
    try {
        assert.match(plain, new RegExp(`Forget retention${' '.repeat(32)}7 days`));
        assert.match(plain, new RegExp(`USER\\.md capacity${' '.repeat(32)}Unlimited`));
        assert.match(plain, new RegExp(`Automatic forgetting${' '.repeat(28)}idle_capacity`));
        assert.doesNotMatch(plain, /Ask Sonex anything|gpt-test/);
    } finally {
        app.unmount();
        stdin.destroy();
        stdout.destroy();
    }
});

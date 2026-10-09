export const ALT_SCREEN_ENTER = '\u001B[?1049h\u001B[2J\u001B[H';
export const ALT_SCREEN_CLEAR = '\u001B[2J\u001B[H';
export const ALT_SCREEN_LEAVE = '\u001B[?1049l';
export const MOUSE_TRACKING_DISABLE = '\u001B[?1006l\u001B[?1000l';
export const CURSOR_SHOW = '\u001B[?25h';

export type TerminalSurface = 'main' | 'alternate';

type TerminalSurfaceOptions = {
    isTTY: boolean;
    write: (value: string) => void;
    resetFrame: () => void;
};

export class TerminalSurfaceController {
    private surface: TerminalSurface = 'main';
    private rendererClear: () => void = () => undefined;
    private disposed = false;

    constructor(private readonly options: TerminalSurfaceOptions) {}

    attachRendererClear(clear: () => void): void {
        this.rendererClear = clear;
    }

    prepare(): void {
        if (this.options.isTTY) {
            this.options.write(MOUSE_TRACKING_DISABLE);
        }
    }

    transition(next: TerminalSurface, commit: (surface: TerminalSurface) => void): void {
        if (this.disposed) return;
        if (!this.options.isTTY) {
            this.surface = 'main';
            commit('main');
            return;
        }

        if (next === this.surface && next === 'main') {
            commit('main');
            return;
        }

        try {
            this.rendererClear();
            this.options.resetFrame();

            if (next === 'alternate' && this.surface === 'main') {
                this.surface = 'alternate';
                this.options.write(ALT_SCREEN_ENTER);
            } else if (next === 'alternate') {
                this.options.write(ALT_SCREEN_CLEAR);
            } else {
                this.options.write(ALT_SCREEN_LEAVE);
                this.surface = 'main';
            }

            commit(this.surface);
        } catch (error) {
            this.dispose();
            throw error;
        }
    }

    dispose(): void {
        if (this.disposed) return;
        this.disposed = true;

        if (!this.options.isTTY) {
            this.bestEffort(this.options.resetFrame);
            this.surface = 'main';
            return;
        }

        this.bestEffort(this.rendererClear);
        this.bestEffort(this.options.resetFrame);
        const leave = this.surface === 'alternate' ? ALT_SCREEN_LEAVE : '';
        this.bestEffort(() => {
            this.options.write(`${leave}${MOUSE_TRACKING_DISABLE}${CURSOR_SHOW}`);
        });
        this.surface = 'main';
    }

    private bestEffort(operation: () => void): void {
        try {
            operation();
        } catch {
            // Terminal restoration must continue even if one cleanup step fails.
        }
    }
}

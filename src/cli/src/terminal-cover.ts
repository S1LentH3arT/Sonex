import { randomInt } from 'node:crypto';
import type { CoverImageEvent } from './types.js';

const MARKER = /\u001b\]777;sonex-cover=(\d+),(\d+),(\d+)\u0007/g;
const command = (control: string, data = ''): string => `\u001b_G${control};${data}\u001b\\`;

export const supportsKittyGraphics = (env = process.env): boolean => (
    !env.TMUX && !env.STY && (env.TERM === 'xterm-kitty' || Boolean(env.KITTY_WINDOW_ID))
);

export function coverSize(image: CoverImageEvent, width: number, height: number) {
    // ponytail: conventional 1:2 cells; use measured pixels when terminal probing is added.
    const scale = Math.min(width / image.width, height * 2 / image.height);
    return {
        columns: Math.max(1, Math.floor(image.width * scale)),
        rows: Math.max(1, Math.floor(image.height * scale / 2)),
    };
}

/** One output stream owns cover uploads and placements; React only emits anchors. */
export class TerminalCover {
    private nextId = randomInt(0x40000000, 0x7fffffff);
    private readonly images = new Map<number, { data: string; uploaded: boolean; placed: boolean }>();

    constructor(readonly enabled: boolean, private readonly write: (value: string) => void) {}

    retain(image: CoverImageEvent): number | null {
        if (!this.enabled || image.format !== 'png'
            || ![image.width, image.height].every(value => Number.isSafeInteger(value) && value > 0 && value <= 640)
            || typeof image.data !== 'string' || image.data.length > 2_796_204
            || image.data.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(image.data)) return null;
        const id = this.nextId++;
        this.images.set(id, { data: image.data, uploaded: false, placed: false });
        return id;
    }

    marker(id: number, columns: number, rows: number): string {
        return `\u001b]777;sonex-cover=${id},${columns},${rows}\u0007`;
    }

    transform(chunk: string): string {
        const cleanup = chunk.includes('\u001b[2J') ? this.clearPlacements() : '';
        return cleanup + chunk.replace(MARKER, (_match, key: string, width: string, height: string) => {
            const id = Number(key);
            const image = this.images.get(id);
            const columns = Number(width);
            const rows = Number(height);
            if (!image || columns < 1 || columns > 640 || rows < 1 || rows > 640) return '';
            let output = '';
            if (!image.uploaded) {
                for (let offset = 0; offset < image.data.length; offset += 4096) {
                    const more = offset + 4096 < image.data.length ? 1 : 0;
                    output += command(`${offset === 0 ? `a=t,f=100,i=${id},` : ''}q=2,m=${more}`, image.data.slice(offset, offset + 4096));
                }
                image.uploaded = true;
            }
            if (image.placed) output += command(`a=d,d=i,i=${id},p=1,q=2`);
            // C=1 leaves the text cursor untouched. The reserved Box owns these cells.
            output += command(`a=p,i=${id},p=1,c=${columns},r=${rows},C=1,q=2`);
            image.placed = true;
            return output;
        });
    }

    release(id: number): void {
        const image = this.images.get(id);
        this.images.delete(id);
        if (image?.uploaded) this.write(command(`a=d,d=I,i=${id},q=2`));
    }

    private clearPlacements(): string {
        let output = '';
        for (const [id, image] of this.images) {
            if (image.placed) output += command(`a=d,d=i,i=${id},p=1,q=2`);
            image.placed = false;
        }
        return output;
    }

    reset(): void {
        const output = this.clearPlacements();
        if (output) this.write(output);
    }

    dispose(): void {
        for (const id of this.images.keys()) this.release(id);
    }
}

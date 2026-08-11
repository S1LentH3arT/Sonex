import type { ChatDocument, ChatSegment } from './types.js';

export function chatDocumentSegments(document: ChatDocument): ChatSegment[] {
    const segments: ChatSegment[] = [];
    const append = (segment: ChatSegment) => {
        if (!segment.text) return;
        const previous = segments[segments.length - 1];
        if (previous?.style === segment.style && previous.href === segment.href) {
            previous.text += segment.text;
        } else {
            segments.push({ ...segment });
        }
    };

    document.blocks.forEach((block, index) => {
        if (block.type === 'spacer') {
            append({ text: '\n', style: 'plain' });
            return;
        }
        if (block.type === 'code_block') {
            append({ text: block.text, style: 'code' });
        } else {
            if (block.type === 'list_item') {
                const level = Math.max(0, Math.min(2, Math.floor(block.level ?? 0)));
                append({ text: `${'  '.repeat(level)}${block.marker} `, style: 'list_marker' });
            }
            for (const span of block.spans) {
                append({
                    text: span.text,
                    style: block.type === 'heading' ? 'heading' : span.style,
                    ...(span.href ? { href: span.href } : {}),
                });
            }
        }
        if (index < document.blocks.length - 1) {
            append({ text: '\n', style: 'plain' });
        }
    });
    return segments;
}

import React from 'react';
import { Box, Text, useStdout } from 'ink';
import { coverSize, type TerminalCover } from './terminal-cover.js';
import type { CoverImageEvent } from './types.js';

export function useCoverArt(image: CoverImageEvent | null, width = 32, height = 16): React.ReactNode {
    const { stdout } = useStdout();
    const cover = (stdout as typeof stdout & { cover?: TerminalCover }).cover;
    const [handle, setHandle] = React.useState<{ image: CoverImageEvent; id: number } | null>(null);

    React.useEffect(() => {
        const id = image && cover?.retain(image);
        setHandle(id == null ? null : { image: image!, id });
        return () => { if (id != null) cover?.release(id); };
    }, [cover, image]);

    if (!image || handle?.image !== image || !cover) return null;
    const { columns, rows } = coverSize(image, width, height);
    return (
        <Box width={columns} height={rows} flexShrink={0}>
            <Text>{cover.marker(handle.id, columns, rows)}{' '}</Text>
        </Box>
    );
}

import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');

assert.equal(source.includes('compact ? "Playing"'), false);
assert.equal(source.includes('<Text bold color={visual.accent}>Playing</Text>'), false);
assert.match(source, /const CoverPatternArt = React\.memo/);
assert.match(source, /React\.useMemo\(\(\) => renderCoverPatternHalfBlocks/);
assert.match(source, /const hasCoverPattern = Boolean\(coverPattern && terminalSpace && chosenPattern\)/);
assert.match(source, /const fetchableCoverUrl = !hasCoverPattern && isHttpCoverSource\(coverUrl\) \? coverUrl : null/);
assert.match(source, /useCoverArt\(fetchableCoverUrl/);
assert.match(source, /const PlaybackProgressTime = React\.memo/);
assert.match(source, /const MiniPlaybackMeter = React\.memo/);
assert.match(source, /const progressBar = buildProgressBar\(player\.progress_ms \?\? 0, player\.duration_ms, 14\)/);
assert.match(source, /const PlaybackMeter = \(\{player, visual, compact = false\}/);
assert.match(source, /if \(compact\) \{\s+return <MiniPlaybackMeter player=\{player\} visual=\{visual\}\/>;\s+\}/);
assert.match(source, /const progressMs = usePlaybackProgress\(player\)/);
assert.match(source, /<PlayerPane player=\{player\} coverUrl=\{coverUrl\} coverPattern=\{coverPattern\} terminalSpace=\{terminalSpace\}\/>/);

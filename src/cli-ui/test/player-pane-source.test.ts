import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Defines the source constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/player-pane-source.test.ts.
 */
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
assert.match(source, /const MiniPlayerStaticBody = React\.memo/);
assert.match(source, /prev\.name === next\.name/);
assert.match(source, /prev\.artist === next\.artist/);
assert.match(source, /prev\.album === next\.album/);
assert.match(source, /const progressMs = player\.progress_ms \?\? 0/);
assert.match(source, /const progressBar = buildProgressBar\(progressMs, player\.duration_ms, 14\)/);
assert.match(source, /const PlaybackMeter = \(\{ player, visual, compact = false, active = true \}:/);
assert.match(source, /if \(compact\) \{\s+return <MiniPlaybackMeter player=\{player\} visual=\{visual\} \/>;\s+\}/);
assert.match(source, /const progressMs = usePlaybackProgress\(player, active\)/);
assert.match(source, /player=\{miniSnapshot\.player\}/);
assert.match(source, /player=\{chatSnapshot\.player\}/);
assert.match(source, /active=\{miniVisible\}/);
assert.match(source, /active=\{showPlaybackSidebar\}/);

/**
 * Defines the mini branch start constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/player-pane-source.test.ts.
 */
const miniBranchStart = source.indexOf('<Box display={miniVisible ? "flex" : "none"}');
/**
 * Defines the mini branch end constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/player-pane-source.test.ts.
 */
const miniBranchEnd = source.indexOf('<Box display={chatVisible ? "flex" : "none"}', miniBranchStart);
assert.ok(miniBranchStart >= 0);
assert.ok(miniBranchEnd > miniBranchStart);
/**
 * Defines the mini branch constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/player-pane-source.test.ts.
 */
const miniBranch = source.slice(miniBranchStart, miniBranchEnd);
assert.equal(miniBranch.includes('<MiniPlayerInputDock'), false);
assert.match(source, /const miniSnapshot = useVisibleSnapshotOnRevision/);
assert.match(source, /}, miniVisible, miniSnapshotRevision\)/);

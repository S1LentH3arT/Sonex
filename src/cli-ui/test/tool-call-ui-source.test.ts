import assert from 'node:assert/strict';
import fs from 'node:fs';

const appSource = fs.readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentsSource = fs.readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const typesSource = fs.readFileSync(new URL('../src/types.ts', import.meta.url), 'utf8');

assert.match(
    componentsSource,
    /confirm\.variant === "tool_call_review"[\s\S]*title=\{confirm\.message\}[\s\S]*Please review the Bash command\(s\) below before permission\./,
);
assert.match(
    componentsSource,
    /wrapChatMessageContent\(command, contentWidth\)[\s\S]*color: TOOL_VALUE/,
);
assert.doesNotMatch(
    componentsSource.slice(
        componentsSource.indexOf('if (confirm.variant === "tool_call_review")'),
        componentsSource.indexOf('if (isSongCandidateConfirm)'),
    ),
    /text:\s*["'`]Bash/,
);
assert.match(
    componentsSource,
    /useToolSegmentStyles && segment\.style === "tool_name"\s*\? TOOL_NAVY[\s\S]*bold=\{[\s\S]*useToolSegmentStyles && segment\.style === "tool_name"/,
);
assert.match(
    appSource,
    /if \(!isMusicConnection && confirm\.variant !== "tool_call_review"\) \{\s*appendPanelHiddenNotice/,
);
assert.match(typesSource, /variant\?: "tool_call_review"/);
assert.match(typesSource, /segments\?: ChatSegment\[\]/);

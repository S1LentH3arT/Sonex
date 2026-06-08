# Cover Palette and Tab Clear Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand static cover bead art to a fixed 96-color palette and clear stale terminal output before accepted Tab layout switches.

**Architecture:** Keep backend quantization authoritative and preserve indexed pattern payloads. Add a pure CLI stdout helper for ANSI clearing, then call it immediately before the existing mini-player focus state transition.

**Tech Stack:** Python 3.12, Pillow, TypeScript, React, Ink, Node test runner.

---

### Task 1: Expand the fixed cover palette

**Files:**
- Modify: `src/tools/cover_patterns.py`
- Modify: `tests/test_cover_patterns.py`

- [ ] **Step 1: Write failing palette tests**

Assert that `COVER_PATTERN_PALETTE` has 96 unique `#rrggbb` entries and that generated grids permit indices below the new palette length.

- [ ] **Step 2: Run the focused test**

Run: `.venv/bin/python -m unittest tests.test_cover_patterns`

Expected: FAIL because the current palette contains 48 colors.

- [ ] **Step 3: Add 48 fixed colors**

Extend `COVER_PATTERN_PALETTE` with intermediate neutral, warm, green, cyan, blue, violet, and magenta shades. Preserve existing entries and weighted nearest-color quantization.

- [ ] **Step 4: Verify palette behavior**

Run: `.venv/bin/python -m unittest tests.test_cover_patterns`

Expected: PASS with 96 unique colors and valid generated indices.

- [ ] **Step 5: Commit**

```bash
git add src/tools/cover_patterns.py tests/test_cover_patterns.py
git commit -m "feat(cover): expand bead palette"
```

### Task 2: Clear terminal output before Tab layout changes

**Files:**
- Modify: `src/cli-ui/src/App.tsx`
- Create: `src/cli-ui/src/terminal-clear.ts`
- Create: `src/cli-ui/test/terminal-clear.test.ts`
- Modify: `src/cli-ui/test/static-banner-source.test.ts`

- [ ] **Step 1: Write failing clear tests**

Test a pure `clearTerminalForLayoutSwitch(stdout)` helper that writes `\u001B[2J\u001B[H` once. Add a source regression assertion that the Tab branch calls the helper before `setSmallPlaybackFocus`.

- [ ] **Step 2: Run focused CLI tests**

Run: `npx tsx --test src/cli-ui/test/terminal-clear.test.ts src/cli-ui/test/static-banner-source.test.ts`

Expected: FAIL because the helper and call do not exist.

- [ ] **Step 3: Implement the clear helper and integration**

Export the helper from `terminal-clear.ts`, import it in `App.tsx`, and invoke it in the accepted playback Tab branch immediately before toggling focus.

- [ ] **Step 4: Verify CLI behavior**

Run: `npm --prefix src/cli-ui test`

Run: `npm --prefix src/cli-ui run build`

Expected: all tests pass and TypeScript builds.

- [ ] **Step 5: Commit**

```bash
git add src/cli-ui/src/App.tsx src/cli-ui/src/terminal-clear.ts src/cli-ui/test/terminal-clear.test.ts src/cli-ui/test/static-banner-source.test.ts
git commit -m "fix(cli-ui): clear screen on tab switch"
```

### Task 3: Final verification

**Files:**
- Verify all files changed by Tasks 1 and 2.

- [ ] **Step 1: Run Python verification**

Run: `.venv/bin/python -m pytest`

Expected: PASS.

- [ ] **Step 2: Run CLI verification**

Run: `npm --prefix src/cli-ui test`

Run: `npm --prefix src/cli-ui run build`

Expected: all tests and build pass.

- [ ] **Step 3: Check repository diff**

Run: `git diff --check`

Expected: no whitespace errors.

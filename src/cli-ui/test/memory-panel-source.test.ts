import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const components = readFileSync(new URL("../src/components.tsx", import.meta.url), "utf8");

assert.match(components, /\["view memory entries", "reset memory"\]/);
assert.match(components, /\["USER\.md", "MEMORY\.md", "Memory Dump"\]/);
assert.match(components, /panel\.view === "format"[\s\S]*\["USER\.md", "MEMORY\.md", "All memory"\]/);
assert.match(components, /const MEMORY_SETTING_LABEL_WIDTH = 48;/);
assert.match(components, /fitDisplayWidth\(label, MEMORY_SETTING_LABEL_WIDTH\)/);
assert.match(components, /formatMemorySettingRow\("Forget retention",/);
assert.doesNotMatch(components, /Disable long-term memory/);
assert.match(app, /action: "revisions"/);
assert.match(app, /action: "restore_revision"/);
assert.match(app, /mode: "setting"/);
assert.match(components, /Math\.min\(74, Math\.floor\(panelWidth\)\)/);
assert.doesNotMatch(components, /if \(activeRegion === "memoryPanel" && memoryPanel\)/);
assert.match(components, /\{memoryPanel \? \([\s\S]*<MemoryPanelOverlay/);
assert.match(components, /\{!memoryPanel \? \([\s\S]*<InputDock/);
assert.match(components, /memoryPanel=\{activeRegion === "memoryPanel" \? memoryPanel : null\}/);
assert.match(app, /nextRegion === "chat" \|\| nextRegion === "memoryPanel" \? "main" : "alternate"/);
assert.match(app, /activeRegionRef\.current === "chat" \|\| activeRegionRef\.current === "memoryPanel"/);
assert.match(app, /activeRegion === "chat" \|\| activeRegion === "memoryPanel" \? undefined : dynamicSurfaceHeight/);

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const components = readFileSync(new URL("../src/components.tsx", import.meta.url), "utf8");

assert.match(components, /\["View memory entries", "Format memory"\]/);
assert.match(components, /\["USER\.md", "MEMORY\.md", "Memory Dump"\]/);
assert.doesNotMatch(components, /Disable long-term memory/);
assert.match(app, /action: "revisions"/);
assert.match(app, /action: "restore_revision"/);
assert.match(app, /mode: "setting"/);
assert.match(components, /Math\.min\(74, Math\.floor\(panelWidth\)\)/);

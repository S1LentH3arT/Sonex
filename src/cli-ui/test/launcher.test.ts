import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import test from "node:test";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

test("published launcher reports its package version without provisioning", () => {
  const output = execFileSync(process.execPath, [resolve(packageRoot, "bin/sonex.js"), "--version"], {
    encoding: "utf8",
  });
  assert.equal(output.trim(), "v0.1.0-alpha.4");
});

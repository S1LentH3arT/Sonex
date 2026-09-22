#!/usr/bin/env node

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync, chmodSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packageJson = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));
const appVersion = packageJson.version;
const uvVersion = "0.12.8";
const uvAssets = {
  x64: {
    name: "uv-x86_64-unknown-linux-gnu.tar.gz",
    sha256: "2e2b37e9811e17675a9e70bed5e1a58fc8c0388be63d751d72cc735188c149ff",
  },
  arm64: {
    name: "uv-aarch64-unknown-linux-gnu.tar.gz",
    sha256: "ba8661f4fd207c8e94814191598e619b355ac10d5014e851e21eb800f9ef2b00",
  },
};

function fail(message, error) {
  console.error(`Sonex setup failed: ${message}`);
  if (process.env.SONEX_DEBUG && error) console.error(error.stack || error);
  process.exit(1);
}

function runtimeRoot() {
  const home = process.env.SONEX_HOME || join(homedir(), ".sonex");
  return resolve(process.env.SONEX_RUNTIME_HOME || join(home, "runtime", "app"));
}

function runtimeDir() {
  return join(runtimeRoot(), appVersion);
}

function executablePath(dir, name) {
  return join(dir, "venv", "bin", name);
}

function runtimeReady(dir) {
  const python = join(dir, "venv", "bin", "python");
  const command = executablePath(dir, "sonex");
  if (!existsSync(join(dir, "runtime.json")) || !existsSync(python) || !existsSync(command)) return false;
  try {
    const marker = JSON.parse(readFileSync(join(dir, "runtime.json"), "utf8"));
    const shebang = readFileSync(command, "utf8").split("\n", 1)[0];
    return marker.appVersion === appVersion && shebang === `#!${python}`;
  } catch {
    return false;
  }
}

function findWheel() {
  const vendor = join(packageRoot, "vendor");
  if (!existsSync(vendor)) return null;
  const wheels = readdirSync(vendor).filter((entry) => entry.startsWith("sonex-") && entry.endsWith(".whl"));
  return wheels.length === 1 ? join(vendor, wheels[0]) : null;
}

function requirementsFile() {
  const candidate = join(packageRoot, "vendor", "requirements-linux-py312.txt");
  return existsSync(candidate) ? candidate : null;
}

function run(command, args, env) {
  const result = spawnSync(command, args, { env, stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} exited with status ${result.status}`);
}

async function download(url, destination) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch(url, { signal: controller.signal, redirect: "follow" });
    if (!response.ok) throw new Error(`HTTP ${response.status} while downloading ${url}`);
    const bytes = Buffer.from(await response.arrayBuffer());
    writeFileSync(destination, bytes, { mode: 0o600 });
    return bytes;
  } finally {
    clearTimeout(timeout);
  }
}

function findFile(root, name) {
  for (const entry of readdirSync(root)) {
    const path = join(root, entry);
    if (statSync(path).isDirectory()) {
      const found = findFile(path, name);
      if (found) return found;
    } else if (entry === name) {
      return path;
    }
  }
  return null;
}

async function ensureUv(toolsDir) {
  const override = process.env.SONEX_UV_BIN;
  if (override) return resolve(override);

  const asset = uvAssets[process.arch];
  if (!asset) throw new Error(`Unsupported Linux architecture: ${process.arch}`);

  const uvPath = join(toolsDir, "uv");
  if (existsSync(uvPath)) return uvPath;

  mkdirSync(toolsDir, { recursive: true, mode: 0o700 });
  const staging = mkdtempSync(join(tmpdir(), "sonex-uv-"));
  const archive = join(staging, asset.name);
  try {
    const url = `https://releases.astral.sh/github/uv/releases/download/${uvVersion}/${asset.name}`;
    const bytes = await download(url, archive);
    const digest = createHash("sha256").update(bytes).digest("hex");
    if (digest !== asset.sha256) throw new Error(`SHA-256 mismatch for ${asset.name}`);

    const extracted = join(staging, "extracted");
    mkdirSync(extracted);
    const result = spawnSync("tar", ["-xzf", archive, "-C", extracted], { stdio: "inherit" });
    if (result.status !== 0) throw new Error("tar failed while unpacking uv");
    const unpacked = findFile(extracted, "uv");
    if (!unpacked) throw new Error("uv executable was not found in the archive");
    renameSync(unpacked, uvPath);
    chmodSync(uvPath, 0o700);
    return uvPath;
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
}

async function installRuntime(target) {
  const wheel = findWheel();
  const requirements = requirementsFile();
  if (!wheel || !requirements) {
    throw new Error("This npm package has no bundled Python runtime artifacts; use a published release package.");
  }

  mkdirSync(runtimeRoot(), { recursive: true, mode: 0o700 });
  if (existsSync(target) && !runtimeReady(target)) renameSync(target, `${target}.incomplete-${Date.now()}`);
  mkdirSync(target, { recursive: true, mode: 0o700 });
  const env = { ...process.env, UV_PYTHON_INSTALL_DIR: join(target, "python") };
  const uv = await ensureUv(join(target, "tools"));
  run(uv, ["python", "install", "3.12", "--install-dir", join(target, "python"), "--no-bin"], env);
  run(uv, ["venv", "--python", "3.12", join(target, "venv")], env);
  const python = join(target, "venv", "bin", "python");
  run(uv, ["pip", "install", "--python", python, "--requirement", requirements], env);
  run(uv, ["pip", "install", "--python", python, "--no-deps", wheel], env);
  writeFileSync(join(target, "runtime.json"), JSON.stringify({ appVersion, python: "3.12", uv: uvVersion }, null, 2) + "\n", { mode: 0o600 });
  return target;
}

function lockOwnerAlive(lockPath) {
  try {
    const owner = JSON.parse(readFileSync(join(lockPath, "owner.json"), "utf8"));
    process.kill(owner.pid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
}

function sleep(milliseconds) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));
}

async function acquireInstallLock(target) {
  const lockPath = `${target}.lock`;
  const started = Date.now();
  mkdirSync(runtimeRoot(), { recursive: true, mode: 0o700 });
  while (true) {
    try {
      mkdirSync(lockPath, { mode: 0o700 });
      writeFileSync(join(lockPath, "owner.json"), JSON.stringify({ pid: process.pid }) + "\n", { mode: 0o600 });
      return () => rmSync(lockPath, { recursive: true, force: true });
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      if (!lockOwnerAlive(lockPath)) {
        renameSync(lockPath, `${lockPath}.stale-${Date.now()}`);
        continue;
      }
      if (Date.now() - started > 10 * 60 * 1000) throw new Error("another Sonex runtime installation is still in progress");
      await sleep(250);
      if (runtimeReady(target)) return () => {};
    }
  }
}

async function ensureRuntime() {
  const target = runtimeDir();
  if (runtimeReady(target)) return target;
  const releaseLock = await acquireInstallLock(target);
  try {
    if (runtimeReady(target)) return target;
    console.error(`Preparing Sonex Python runtime ${appVersion}...`);
    return await installRuntime(target);
  } finally {
    releaseLock();
  }
}

function launch(runtime) {
  const command = executablePath(runtime, "sonex");
  const child = spawn(command, process.argv.slice(2), {
    cwd: process.cwd(),
    env: {
      ...process.env,
      SONEX_APP_VERSION: appVersion,
      SONEX_CLI_UI_DIR: packageRoot,
      SONEX_NODE: process.execPath,
      SONEX_RUNTIME_DIR: runtime,
      SONEX_YOUTUBE_RUNTIME_DIR: join(packageRoot, "vendor", "youtube-runtime"),
    },
    stdio: "inherit",
  });

  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(signal, () => child.kill(signal));
  }
  child.on("error", (error) => fail(`could not start ${command}`, error));
  child.on("exit", (code, signal) => {
    if (signal) process.exit(128 + (signal === "SIGINT" ? 2 : signal === "SIGTERM" ? 15 : 1));
    process.exit(code ?? 1);
  });
}

if (process.argv.length === 3 && ["--version", "-v"].includes(process.argv[2])) {
  console.log(`v${appVersion}`);
} else if (process.platform !== "linux") {
  fail("this alpha release supports Linux and WSL2 only");
} else {
  ensureRuntime().then(launch).catch((error) => fail(error.message, error));
}

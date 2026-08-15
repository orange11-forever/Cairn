import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { spawnInvocation } from "./spawn-command.mjs";

const REPOSITORY_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const PNPM = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const UV = process.platform === "win32" ? "uv.exe" : "uv";

const TASKS = Object.freeze({
  "test:contracts": [PNPM, ["--filter", "@cairn/contracts", "test"]],
  "typecheck:contracts": [PNPM, ["--filter", "@cairn/contracts", "typecheck"]],
  "generate:sdk": [process.execPath, ["scripts/generate-sdk.mjs"]],
  "check:sdk": [process.execPath, ["scripts/generate-sdk.mjs", "--check"]],
  "test:sdk": [PNPM, ["--filter", "@cairn/sdk", "test"]],
  "typecheck:sdk": [PNPM, ["--filter", "@cairn/sdk", "typecheck"]],
  "dev:web": [PNPM, ["--filter", "cairn-web", "dev"]],
  "dev:core": [process.execPath, ["scripts/dev-core.mjs"]],
  "mock:web": [PNPM, ["--filter", "cairn-web", "mock"]],
  "test:web": [PNPM, ["--filter", "cairn-web", "test"]],
  "typecheck:web": [PNPM, ["--filter", "cairn-web", "typecheck"]],
  "build:web": [PNPM, ["--filter", "cairn-web", "build"]],
  "verify:web": [PNPM, ["--filter", "cairn-web", "verify"]],
  "verify:auth-proxy": [process.execPath, ["scripts/verify-auth-proxy.mjs"]],
  "dev:api": [UV, ["run", "--package", "cairn-api", "cairn-api"]],
  "auth:cleanup": [UV, ["run", "--package", "cairn-api", "cairn-api", "auth-cleanup"]],
  "test:api": [UV, ["run", "--package", "cairn-api", "pytest", "apps/api/tests", "-q"]],
  "lint:api": [
    UV,
    ["run", "--package", "cairn-api", "ruff", "check", "apps/api/src", "apps/api/tests"],
  ],
  "typecheck:api": [UV, ["run", "--package", "cairn-api", "pyright"]],
  "build:api": [UV, ["build", "--package", "cairn-api"]],
  "db:migrate": [
    UV,
    ["run", "--package", "cairn-api", "alembic", "-c", "apps/api/alembic.ini", "upgrade", "head"],
  ],
  "db:seed": [UV, ["run", "--package", "cairn-api", "python", "-m", "cairn_api.seed"]],
  "dev:worker": ["uv", ["run", "--package", "cairn-worker", "cairn-worker", "serve"]],
  "worker:once": ["uv", ["run", "--package", "cairn-worker", "cairn-worker", "--once"]],
  "worker:preflight": [
    "uv",
    ["run", "--package", "cairn-worker", "cairn-worker", "preflight"],
  ],
  "test:worker": [
    "uv",
    ["run", "--package", "cairn-worker", "pytest", "apps/worker/tests", "-q"],
  ],
  "lint:worker": [
    "uv",
    ["run", "--package", "cairn-worker", "ruff", "check", "apps/worker/src", "apps/worker/tests"],
  ],
  "typecheck:worker": ["uv", ["run", "--package", "cairn-worker", "pyright"]],
  "infra:up": [process.execPath, ["scripts/infra.mjs", "up"]],
  "verify:core": [process.execPath, ["scripts/verify-core.mjs"]],
});

export function taskInvocation(taskName, platform = process.platform) {
  const task = TASKS[taskName];
  if (task === undefined) return undefined;
  const [command, args] = task;
  if (command === "uv" || command === "uv.exe") {
    return [platform === "win32" ? "uv.exe" : "uv", [...args]];
  }
  return [command, [...args]];
}

export function runTask(taskName) {
  const task = taskInvocation(taskName);
  if (task === undefined) {
    console.error(`Unknown task: ${taskName}`);
    return Promise.resolve(2);
  }

  const [command, args] = task;
  return new Promise((resolveExitCode) => {
    const invocation = spawnInvocation(command, args);
    const child = spawn(invocation.command, invocation.args, {
      cwd: REPOSITORY_ROOT,
      shell: false,
      stdio: "inherit",
    });

    child.once("error", (error) => {
      console.error(`Failed to start ${taskName}: ${error.message}`);
      resolveExitCode(1);
    });
    child.once("exit", (code, signal) => {
      resolveExitCode(signal === null ? (code ?? 1) : 1);
    });
  });
}

const entryPath = process.argv[1];
const isMain = entryPath !== undefined && resolve(entryPath) === fileURLToPath(import.meta.url);

if (isMain) {
  const taskNames = process.argv.slice(2);
  if (taskNames.length !== 1) {
    console.error("Usage: node scripts/run-task.mjs <task>");
    process.exitCode = 2;
  } else {
    process.exitCode = await runTask(taskNames[0]);
  }
}

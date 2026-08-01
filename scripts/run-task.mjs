import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPOSITORY_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const PNPM = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const UV = process.platform === "win32" ? "uv.exe" : "uv";

const TASKS = Object.freeze({
  "dev:web": [PNPM, ["--filter", "cairn-web", "dev"]],
  "mock:web": [PNPM, ["--filter", "cairn-web", "mock"]],
  "test:web": [PNPM, ["--filter", "cairn-web", "test"]],
  "typecheck:web": [PNPM, ["--filter", "cairn-web", "typecheck"]],
  "build:web": [PNPM, ["--filter", "cairn-web", "build"]],
  "verify:web": [PNPM, ["--filter", "cairn-web", "verify"]],
  "dev:api": [UV, ["run", "--package", "cairn-api", "cairn-api"]],
  "test:api": [UV, ["run", "--package", "cairn-api", "pytest", "apps/api/tests", "-q"]],
  "lint:api": [
    UV,
    ["run", "--package", "cairn-api", "ruff", "check", "apps/api/src", "apps/api/tests"],
  ],
  "typecheck:api": [UV, ["run", "--package", "cairn-api", "pyright"]],
  "build:api": [UV, ["build", "--package", "cairn-api"]],
});

export function runTask(taskName) {
  const task = TASKS[taskName];
  if (task === undefined) {
    console.error(`Unknown task: ${taskName}`);
    return Promise.resolve(2);
  }

  const [command, args] = task;
  return new Promise((resolveExitCode) => {
    const child = spawn(command, args, {
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

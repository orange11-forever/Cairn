import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  settleCleanupTasks,
  stopProcessTree,
  waitForServer,
} from "../apps/web/scripts/process-utils.mjs";
import { runTask as runRootTask } from "./run-task.mjs";
import { spawnInvocation } from "./spawn-command.mjs";

const REPOSITORY_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const NEVER = new Promise(() => undefined);
const SERVICES = Object.freeze([
  { task: "dev:api", readyUrl: "http://127.0.0.1:8080/ready" },
  { task: "mock:web", readyUrl: "http://localhost:8787/health" },
  { task: "dev:web", readyUrl: "http://localhost:5500/" },
]);

function coreEnvironment(baseEnvironment = process.env) {
  return {
    ...baseEnvironment,
    APP_URL: "http://localhost:5500",
    CORS_ORIGINS: "http://localhost:5500",
    VITE_IDENTITY_API_URL: "http://localhost:8080",
    VITE_MOCK_API_URL: "http://localhost:8787",
  };
}

export function startManagedTask(
  taskName,
  { environment = coreEnvironment(), spawnProcess = spawn } = {},
) {
  const invocation = spawnInvocation(process.execPath, ["scripts/run-task.mjs", taskName]);
  const child = spawnProcess(invocation.command, invocation.args, {
    cwd: REPOSITORY_ROOT,
    detached: process.platform !== "win32",
    env: environment,
    shell: false,
    stdio: "inherit",
  });
  const completion = new Promise((resolveCompletion) => {
    child.once("error", () => resolveCompletion({ code: 1, signal: null }));
    child.once("exit", (code, signal) => resolveCompletion({ code, signal }));
  });

  return {
    name: taskName,
    completion,
    stop: () => stopProcessTree(child),
  };
}

async function stopAll(children, reportError) {
  const failures = await settleCleanupTasks(
    children.map((child) => ({ name: child.name, run: () => child.stop() })),
  );
  for (const failure of failures) {
    reportError(`Failed to stop ${failure.name}: ${String(failure.reason)}`);
  }
}

export async function runDevCore({
  runTask = runRootTask,
  startTask = startManagedTask,
  waitForUrl = waitForServer,
  announce = console.log,
  reportError = console.error,
  termination = NEVER,
} = {}) {
  for (const taskName of ["db:migrate", "db:seed"]) {
    const exitCode = await runTask(taskName);
    if (exitCode !== 0) return exitCode;
  }

  const environment = coreEnvironment();
  const children = [];
  try {
    for (const service of SERVICES) {
      children.push(startTask(service.task, { environment }));
    }
    for (const service of SERVICES) {
      await waitForUrl(service.readyUrl);
    }

    announce("Cairn core is ready: http://localhost:5500");
    announce("Demo account: demo@cairn.dev");

    const completion = await Promise.race([
      termination,
      ...children.map((child) => child.completion),
    ]);
    if (completion?.requested === true) return 0;
    return completion?.signal === null ? (completion.code ?? 1) : 1;
  } catch (error) {
    reportError(error instanceof Error ? error.message : String(error));
    return 1;
  } finally {
    await stopAll(children, reportError);
  }
}

function createTermination() {
  let resolveTermination;
  const promise = new Promise((resolvePromise) => {
    resolveTermination = resolvePromise;
  });
  const onSignal = (signal) => resolveTermination({ requested: true, signal });
  const onInterrupt = () => onSignal("SIGINT");
  const onTerminate = () => onSignal("SIGTERM");
  process.once("SIGINT", onInterrupt);
  process.once("SIGTERM", onTerminate);
  return {
    promise,
    dispose() {
      process.removeListener("SIGINT", onInterrupt);
      process.removeListener("SIGTERM", onTerminate);
    },
  };
}

const entryPath = process.argv[1];
const isMain = entryPath !== undefined && resolve(entryPath) === fileURLToPath(import.meta.url);

if (isMain) {
  const termination = createTermination();
  process.exitCode = await runDevCore({ termination: termination.promise });
  termination.dispose();
}

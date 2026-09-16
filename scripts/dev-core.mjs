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
  { task: "dev:embedding", readyUrl: "http://127.0.0.1:58081/health" },
  { task: "dev:api", readyUrl: "http://127.0.0.1:8080/ready" },
  { task: "dev:worker" },
  { task: "dev:web", readyUrl: "http://localhost:5500/" },
]);

function coreEnvironment(baseEnvironment = process.env) {
  return {
    ...baseEnvironment,
    APP_URL: "http://localhost:5500",
    CORS_ORIGINS: "http://localhost:5500",
    CAIRN_EMBEDDING_PORT: "58081",
    EMBEDDING_API_KEY: "local-fake-embedding-key",
    EMBEDDING_BASE_URL: "http://127.0.0.1:58081/v1",
    EMBEDDING_BATCH_SIZE: "10",
    EMBEDDING_DIM: "1024",
    EMBEDDING_MODEL: "text-embedding-v4",
    EMBEDDING_PROVIDER: "local-fake",
    VITE_IDENTITY_API_URL: "http://localhost:8080",
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

async function waitForManagedReadiness(children, child, readyUrl, waitForUrl, termination) {
  const readiness = await Promise.race([
    waitForUrl(readyUrl).then(() => ({ ready: true })),
    ...children.map((candidate) => candidate.completion.then((completion) => ({
      ready: false,
      exited: candidate.name,
      completion,
    }))),
    termination,
  ]);
  if (readiness?.requested === true) return false;
  if (!readiness.ready) {
    throw new Error(
      `${readiness.exited ?? child.name} exited before ${child.name} readiness `
      + `(code=${readiness.completion.code}, signal=${readiness.completion.signal})`,
    );
  }
  return true;
}

export async function runDevCore({
  runTask = runRootTask,
  startOneShotTask,
  startTask = startManagedTask,
  waitForUrl = waitForServer,
  announce = console.log,
  reportError = console.error,
  termination = NEVER,
} = {}) {
  const environment = coreEnvironment();
  const children = [];
  const startBootstrapTask = startOneShotTask ?? (runTask === runRootTask
    ? startManagedTask
    : (taskName) => ({
        name: taskName,
        completion: runTask(taskName).then((code) => ({ code, signal: null })),
        stop: async () => undefined,
      }));
  try {
    for (const taskName of [
      "db:migrate",
      "object-store-bootstrap",
      "embedding-profile-bootstrap",
      "db:seed",
    ]) {
      const child = startBootstrapTask(taskName, { environment });
      children.push(child);
      const result = await Promise.race([child.completion, termination]);
      if (result?.requested === true) return 0;
      children.pop();
      const exitCode = result.signal === null ? (result.code ?? 1) : 1;
      if (exitCode !== 0) return exitCode;
    }

    const embedding = SERVICES[0];
    const embeddingChild = startTask(embedding.task, { environment });
    children.push(embeddingChild);
    if (!await waitForManagedReadiness(
      children, embeddingChild, embedding.readyUrl, waitForUrl, termination,
    )) return 0;

    for (const service of SERVICES.slice(1)) {
      children.push(startTask(service.task, { environment }));
    }
    for (let index = 1; index < SERVICES.length; index += 1) {
      const service = SERVICES[index];
      if (service.readyUrl === undefined) continue;
      if (!await waitForManagedReadiness(
        children, children[index], service.readyUrl, waitForUrl, termination,
      )) return 0;
    }

    announce("Cairn core is ready: http://localhost:5500");
    announce("Demo account: demo@cairn.dev");

    const completion = await Promise.race([
      termination,
      ...children.map((child) => child.completion),
    ]);
    if (completion?.requested === true) return 0;
    return 1;
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

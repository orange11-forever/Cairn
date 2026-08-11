import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { stopProcessTree, waitForServer } from "../apps/web/scripts/process-utils.mjs";
import { resolveDockerCommand } from "./docker-command.mjs";
import { spawnInvocation } from "./spawn-command.mjs";

const REPOSITORY_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const COMPOSE_FILE = resolve(REPOSITORY_ROOT, "deploy/compose/core.yml");
const UV = process.platform === "win32" ? "uv.exe" : "uv";
const NEVER = new Promise(() => undefined);
const STAGES = Object.freeze([
  "minio",
  "migrate",
  "integration",
  "seed",
  "sdk",
  "api",
  "web-build",
  "production",
  "browser",
]);

function readPort(environment, name, fallback) {
  const raw = environment[name] ?? String(fallback);
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${name} must be an integer between 1 and 65535, received ${raw}`);
  }
  return port;
}

export function createVerificationProjectName({
  pid = process.pid,
  randomBytes: makeRandomBytes = randomBytes,
} = {}) {
  return `cairn-verify-${pid}-${makeRandomBytes(4).toString("hex")}`;
}

export function resolveVerificationConfig(
  environment = process.env,
  { projectName = createVerificationProjectName() } = {},
) {
  if (!/^cairn-(?:verify|test)-[a-z0-9-]+$/.test(projectName)) {
    throw new Error("verification project must match ^cairn-(verify|test)-[a-z0-9-]+$");
  }
  const databasePort = readPort(environment, "CAIRN_VERIFY_POSTGRES_PORT", 55436);
  const apiPort = readPort(environment, "CAIRN_VERIFY_API_PORT", 58080);
  const webPort = readPort(environment, "CAIRN_VERIFY_WEB_PORT", 55500);
  const mockPort = readPort(environment, "CAIRN_VERIFY_MOCK_PORT", 58787);
  const proxyPort = readPort(environment, "CAIRN_VERIFY_PROXY_PORT", 58443);
  const databaseUrl =
    `postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:${databasePort}/cairn_test`;
  const apiOrigin = `http://localhost:${apiPort}`;
  const webOrigin = `http://localhost:${webPort}`;
  const mockOrigin = `http://localhost:${mockPort}`;
  const productionProxyOrigin = `https://localhost:${proxyPort}`;
  const productionApiOrigin = `https://localhost:${apiPort}`;
  const productionWebOrigin = `https://localhost:${webPort}`;
  const productionEnvironment = {
    ...environment,
    APP_URL: productionWebOrigin,
    CAIRN_AUTH_RATE_LIMIT_SECRET: "proxy-verification-rate-limit-secret-at-least-32-bytes",
    CAIRN_CSRF_SECRET: "proxy-verification-csrf-secret-at-least-32-bytes",
    CAIRN_ENVIRONMENT: "production",
    CAIRN_OBJECT_STORE_ACCESS_KEY: "proxy-verification-object-store-access",
    CAIRN_OBJECT_STORE_SECRET_KEY: "proxy-verification-object-store-secret",
    CAIRN_SEARCH_AUDIT_SECRET: "proxy-verification-search-audit-secret-at-least-32-bytes",
    CAIRN_SESSION_COOKIE_SECURE: "true",
    CAIRN_TRUSTED_PROXY_CIDRS: "127.0.0.0/8,::1/128",
    CORS_ORIGINS: productionWebOrigin,
    EMBEDDING_API_KEY: "proxy-verification-embedding-key",
    VITE_IDENTITY_API_URL: productionProxyOrigin,
  };

  return {
    projectName,
    databasePort,
    apiPort,
    webPort,
    mockPort,
    proxyPort,
    databaseUrl,
    apiOrigin,
    webOrigin,
    mockOrigin,
    productionProxyOrigin,
    productionApiOrigin,
    productionWebOrigin,
    productionEnvironment,
    environment: {
      ...environment,
      APP_URL: webOrigin,
      CAIRN_CSRF_SECRET: "test-only-csrf-secret-with-at-least-32-bytes",
      CAIRN_ENVIRONMENT: "test",
      CAIRN_HTTP_PORT: String(apiPort),
      CAIRN_POSTGRES_PORT: String(databasePort),
      CAIRN_SESSION_COOKIE_SECURE: "false",
      CAIRN_TEST_DATABASE_URL: databaseUrl,
      CAIRN_VERIFY_API_PORT: String(apiPort),
      CAIRN_VERIFY_IDENTITY_ORIGIN: apiOrigin,
      CAIRN_VERIFY_MOCK_PORT: String(mockPort),
      CAIRN_VERIFY_PROXY_PORT: String(proxyPort),
      CAIRN_VERIFY_POSTGRES_PORT: String(databasePort),
      CAIRN_VERIFY_WEB_PORT: String(webPort),
      CORS_ORIGINS: webOrigin,
      DATABASE_URL: databaseUrl,
      POSTGRES_DB: "cairn_test",
      POSTGRES_PASSWORD: "cairn-local-only",
      POSTGRES_USER: "cairn",
      VITE_IDENTITY_API_URL: apiOrigin,
      VITE_MOCK_API_URL: mockOrigin,
    },
  };
}

export function createProcessManager({ spawnProcess = spawn } = {}) {
  const active = new Set();

  function start(command, args, options = {}) {
    const invocation = spawnInvocation(command, args);
    const child = spawnProcess(invocation.command, invocation.args, {
      cwd: REPOSITORY_ROOT,
      detached: process.platform !== "win32",
      shell: false,
      stdio: "inherit",
      ...options,
    });
    active.add(child);
    const completion = new Promise((resolveCompletion) => {
      let settled = false;
      const finish = (result) => {
        if (settled) return;
        settled = true;
        active.delete(child);
        resolveCompletion(result);
      };
      child.once("error", () => finish({ code: 1, signal: null }));
      child.once("exit", (code, signal) => finish({ code, signal }));
    });
    return {
      completion,
      stop: () => stopProcessTree(child),
    };
  }

  async function run(command, args, options) {
    const managed = start(command, args, options);
    const result = await managed.completion;
    return result.signal === null ? (result.code ?? 1) : 1;
  }

  async function stopAll() {
    const children = [...active];
    await Promise.allSettled(children.map((child) => stopProcessTree(child)));
  }

  return { run, start, stopAll };
}

function createCompose(config, processManager) {
  let dockerCommandPromise;
  return async (args) => {
    dockerCommandPromise ??= resolveDockerCommand({ env: config.environment });
    const dockerCommand = await dockerCommandPromise;
    return processManager.run(
      dockerCommand,
      ["compose", "-f", COMPOSE_FILE, ...args],
      { env: config.environment },
    );
  };
}

export function createStageRunner(config, processManager) {
  const nodeTask = (task) =>
    processManager.run(
      process.execPath,
      ["scripts/run-task.mjs", task],
      { env: config.environment },
    );

  return async (stage) => {
    if (stage === "minio") {
      return processManager.run(
        process.execPath,
        ["scripts/minio-smoke.mjs"],
        { env: config.environment },
      );
    }
    if (stage === "migrate") return nodeTask("db:migrate");
    if (stage === "integration") {
      const integrationEnvironment = { ...config.environment };
      delete integrationEnvironment.CORS_ORIGINS;
      return processManager.run(
        UV,
        [
          "run",
          "--package",
          "cairn-api",
          "pytest",
          "apps/api/tests/integration",
          "-q",
          "-m",
          "integration",
        ],
        { env: integrationEnvironment },
      );
    }
    if (stage === "seed") return nodeTask("db:seed");
    if (stage === "sdk") return nodeTask("check:sdk");
    if (stage === "api") {
      return processManager.start(
        UV,
        ["run", "--package", "cairn-api", "cairn-api"],
        { env: config.environment },
      );
    }
    if (stage === "web-build") return nodeTask("build:web");
    if (stage === "production") {
      return processManager.run(
        process.execPath,
        ["apps/web/scripts/verify-production-build.mjs"],
        { env: config.environment },
      );
    }
    if (stage === "browser") {
      const browserCode = await processManager.run(
        process.execPath,
        ["apps/web/scripts/verify-web.mjs"],
        { env: config.environment },
      );
      if (browserCode !== 0) return browserCode;
      return processManager.run(
        process.execPath,
        ["scripts/verify-auth-proxy.mjs"],
        { env: config.environment },
      );
    }
    throw new Error(`Unknown core verification stage: ${stage}`);
  };
}

async function waitForManagedApi(api, readyUrl, waitForUrl) {
  const result = await Promise.race([
    waitForUrl(readyUrl).then(() => ({ ready: true })),
    api.completion.then((completion) => ({ ready: false, completion })),
  ]);
  if (!result.ready) {
    throw new Error(
      `Verification API exited before readiness (code=${result.completion.code}, signal=${result.completion.signal})`,
    );
  }
}

export async function runCoreVerification(options = {}) {
  const config = resolveVerificationConfig(options.environment, {
    projectName: options.projectName,
  });
  const processManager = options.processManager ?? createProcessManager();
  const compose = options.compose ?? createCompose(config, processManager);
  const run = options.run ?? createStageRunner(config, processManager);
  const waitForUrl = options.waitForUrl ?? waitForServer;
  const reportError = options.reportError ?? console.error;
  const termination = options.termination ?? NEVER;
  let api = null;
  let exitCode = 0;

  try {
    exitCode = await compose([
      "-p",
      config.projectName,
      "up",
      "-d",
      "--wait",
      "postgres",
    ]);
    if (exitCode === 0) {
      for (const stage of STAGES) {
        const stageResult = await Promise.race([
          run(stage, config),
          termination,
        ]);
        if (stageResult?.requested === true) {
          exitCode = 1;
          break;
        }
        if (stage === "api" && typeof stageResult === "object") {
          api = stageResult;
          await waitForManagedApi(api, `${config.apiOrigin}/ready`, waitForUrl);
          continue;
        }
        exitCode = stageResult;
        if (exitCode !== 0) break;
      }
    }
  } catch (error) {
    reportError(error instanceof Error ? error.message : String(error));
    exitCode = 1;
  } finally {
    if (api !== null) {
      try {
        await api.stop();
      } catch (error) {
        reportError(`Failed to stop verification API: ${String(error)}`);
        exitCode = 1;
      }
    }
    await processManager.stopAll();
    const cleanupCode = await compose([
      "-p",
      config.projectName,
      "down",
      "--volumes",
      "--remove-orphans",
    ]);
    if (cleanupCode !== 0) exitCode = cleanupCode;
  }

  return exitCode;
}

function installSignalHandlers(processManager) {
  let requested = false;
  let resolveTermination;
  const termination = new Promise((resolvePromise) => {
    resolveTermination = resolvePromise;
  });
  const onSignal = (signal) => {
    if (requested) return;
    requested = true;
    void processManager.stopAll().finally(() => {
      resolveTermination({ requested: true, signal });
    });
  };
  const onInterrupt = () => onSignal("SIGINT");
  const onTerminate = () => onSignal("SIGTERM");
  process.on("SIGINT", onInterrupt);
  process.on("SIGTERM", onTerminate);
  return {
    termination,
    dispose() {
      process.removeListener("SIGINT", onInterrupt);
      process.removeListener("SIGTERM", onTerminate);
    },
  };
}

const entryPath = process.argv[1];
const isMain = entryPath !== undefined && resolve(entryPath) === fileURLToPath(import.meta.url);

if (isMain) {
  const processManager = createProcessManager();
  const signals = installSignalHandlers(processManager);
  process.exitCode = await runCoreVerification({
    processManager,
    termination: signals.termination,
  });
  signals.dispose();
}

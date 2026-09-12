import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { stopProcessTree, waitForServer } from "../apps/web/scripts/process-utils.mjs";
import { dockerEnvironment, resolveDockerCommand } from "./docker-command.mjs";
import { spawnInvocation } from "./spawn-command.mjs";

const REPOSITORY_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const COMPOSE_FILE = resolve(REPOSITORY_ROOT, "deploy/compose/core.yml");
const UV = process.platform === "win32" ? "uv.exe" : "uv";
const NEVER = new Promise(() => undefined);
const STAGES = Object.freeze([
  "migrate",
  "object-store-bootstrap",
  "minio",
  "embedding-profile-bootstrap",
  "api-integration",
  "worker-integration",
  "runtime-profile-bootstrap",
  "seed",
  "sdk",
  "embedding",
  "worker-preflight",
  "api",
  "worker",
  "web-build",
  "browser",
  "production",
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
  const minioPort = readPort(environment, "CAIRN_VERIFY_MINIO_PORT", 59000);
  const minioConsolePort = readPort(
    environment,
    "CAIRN_VERIFY_MINIO_CONSOLE_PORT",
    59001,
  );
  const apiPort = readPort(environment, "CAIRN_VERIFY_API_PORT", 58080);
  const embeddingPort = readPort(environment, "CAIRN_VERIFY_EMBEDDING_PORT", 58081);
  const webPort = readPort(environment, "CAIRN_VERIFY_WEB_PORT", 55500);
  const proxyPort = readPort(environment, "CAIRN_VERIFY_PROXY_PORT", 58443);
  const ports = [databasePort, minioPort, minioConsolePort, apiPort, embeddingPort, webPort, proxyPort];
  if (new Set(ports).size !== ports.length) {
    throw new Error("verification service ports must be distinct");
  }
  const databaseUrl =
    `postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:${databasePort}/cairn_test`;
  const objectStoreEndpoint = `http://127.0.0.1:${minioPort}`;
  const apiOrigin = `http://localhost:${apiPort}`;
  const embeddingOrigin = `http://127.0.0.1:${embeddingPort}`;
  const webOrigin = `http://localhost:${webPort}`;
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
    CAIRN_OBJECT_STORE_ENDPOINT_URL: objectStoreEndpoint,
    CAIRN_OBJECT_STORE_PUBLIC_ENDPOINT_URL: objectStoreEndpoint,
    CAIRN_OBJECT_STORE_SECRET_KEY: "proxy-verification-object-store-secret",
    CAIRN_SEARCH_AUDIT_SECRET: "proxy-verification-search-audit-secret-at-least-32-bytes",
    CAIRN_SESSION_COOKIE_SECURE: "true",
    CAIRN_TRUSTED_PROXY_CIDRS: "127.0.0.0/8,::1/128",
    CORS_ORIGINS: productionWebOrigin,
    EMBEDDING_API_KEY: "local-fake-verification-key",
    EMBEDDING_BASE_URL: `${embeddingOrigin}/v1`,
    EMBEDDING_DIM: "1024",
    EMBEDDING_MODEL: "text-embedding-v4",
    EMBEDDING_PROVIDER: "local-fake",
    VITE_IDENTITY_API_URL: productionProxyOrigin,
  };

  return {
    projectName,
    databasePort,
    minioPort,
    minioConsolePort,
    apiPort,
    embeddingPort,
    webPort,
    proxyPort,
    databaseUrl,
    apiOrigin,
    embeddingOrigin,
    webOrigin,
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
      CAIRN_EMBEDDING_PORT: String(embeddingPort),
      CAIRN_MINIO_CONSOLE_PORT: String(minioConsolePort),
      CAIRN_MINIO_PORT: String(minioPort),
      CAIRN_OBJECT_STORE_ACCESS_KEY: "proxy-verification-object-store-access",
      CAIRN_OBJECT_STORE_BUCKET: "cairn-test",
      CAIRN_OBJECT_STORE_ENDPOINT_URL: objectStoreEndpoint,
      CAIRN_OBJECT_STORE_PUBLIC_ENDPOINT_URL: objectStoreEndpoint,
      CAIRN_OBJECT_STORE_SECRET_KEY: "proxy-verification-object-store-secret",
      CAIRN_POSTGRES_PORT: String(databasePort),
      CAIRN_SESSION_COOKIE_SECURE: "false",
      CAIRN_TEST_DATABASE_URL: databaseUrl,
      CAIRN_TEST_CORS_ORIGIN: webOrigin,
      CAIRN_TEST_S3_ENDPOINT_URL: objectStoreEndpoint,
      CAIRN_VERIFY_API_PORT: String(apiPort),
      CAIRN_VERIFY_EMBEDDING_PORT: String(embeddingPort),
      CAIRN_VERIFY_IDENTITY_ORIGIN: apiOrigin,
      CAIRN_VERIFY_PROXY_PORT: String(proxyPort),
      CAIRN_VERIFY_POSTGRES_PORT: String(databasePort),
      CAIRN_VERIFY_MINIO_CONSOLE_PORT: String(minioConsolePort),
      CAIRN_VERIFY_MINIO_PORT: String(minioPort),
      CAIRN_VERIFY_WEB_PORT: String(webPort),
      CORS_ORIGINS: webOrigin,
      DATABASE_URL: databaseUrl,
      EMBEDDING_API_KEY: "local-fake-verification-key",
      EMBEDDING_BASE_URL: `${embeddingOrigin}/v1`,
      EMBEDDING_BATCH_SIZE: "10",
      EMBEDDING_DIM: "1024",
      EMBEDDING_MODEL: "text-embedding-v4",
      EMBEDDING_PROVIDER: "local-fake",
      POSTGRES_DB: "cairn_test",
      POSTGRES_PASSWORD: "cairn-local-only",
      POSTGRES_USER: "cairn",
      CAIRN_AUTH_RATE_LIMIT_SECRET: "verification-rate-limit-secret-at-least-32-bytes",
      CAIRN_SEARCH_AUDIT_SECRET: "verification-search-audit-secret-at-least-32-bytes",
      VITE_IDENTITY_API_URL: apiOrigin,
    },
  };
}

export function createProcessManager({
  spawnProcess = spawn,
  platform = process.platform,
} = {}) {
  const active = new Set();

  function start(command, args, options = {}) {
    const invocation = spawnInvocation(command, args);
    const childEnvironment = dockerEnvironment({
      dockerCommand: invocation.command,
      env: options.env ?? process.env,
      platform,
    });
    const child = spawnProcess(invocation.command, invocation.args, {
      cwd: REPOSITORY_ROOT,
      detached: process.platform !== "win32",
      shell: false,
      stdio: "inherit",
      ...options,
      env: childEnvironment,
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
  const command = async (signal) => {
    dockerCommandPromise ??= resolveDockerCommand({ env: config.environment, signal });
    return dockerCommandPromise;
  };
  const compose = async (args) => {
    const dockerCommand = await command();
    return processManager.run(
      dockerCommand,
      ["compose", "-f", COMPOSE_FILE, ...args],
      { env: config.environment },
    );
  };
  compose.start = async (args, { signal } = {}) => {
    const dockerCommand = await command(signal);
    if (signal?.aborted) throw new Error("Compose startup aborted");
    return processManager.start(
      dockerCommand,
      ["compose", "-f", COMPOSE_FILE, ...args],
      { env: config.environment },
    );
  };
  return compose;
}

export function createStageRunner(config, processManager) {
  const nodeTask = (task) =>
    processManager.run(
      process.execPath,
      ["scripts/run-task.mjs", task],
      { env: config.environment },
    );

  return async (stage) => {
    if (stage === "object-store-bootstrap") {
      return processManager.run(
        UV,
        ["run", "--package", "cairn-api", "cairn-api", "object-store-bootstrap"],
        { env: config.environment },
      );
    }
    if (stage === "minio") {
      return processManager.run(
        process.execPath,
        ["scripts/minio-smoke.mjs"],
        { env: config.environment },
      );
    }
    if (stage === "migrate") return nodeTask("db:migrate");
    if (stage === "embedding-profile-bootstrap") return nodeTask("embedding-profile-bootstrap");
    if (stage === "runtime-profile-bootstrap") return nodeTask("embedding-profile-bootstrap");
    if (stage === "api-integration") {
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
    if (stage === "worker-integration") {
      const integrationEnvironment = { ...config.environment };
      delete integrationEnvironment.CORS_ORIGINS;
      return processManager.run(
        UV,
        [
          "run",
          "--package",
          "cairn-worker",
          "pytest",
          "apps/worker/tests/integration",
          "-q",
          "-m",
          "integration",
        ],
        { env: integrationEnvironment },
      );
    }
    if (stage === "seed") return nodeTask("db:seed");
    if (stage === "sdk") return nodeTask("check:sdk");
    if (stage === "embedding") {
      return processManager.start(
        process.execPath,
        ["scripts/fake-embedding.mjs"],
        { env: config.environment },
      );
    }
    if (stage === "worker-preflight") return nodeTask("worker:preflight");
    if (stage === "api") {
      return processManager.start(
        UV,
        ["run", "--package", "cairn-api", "cairn-api"],
        { env: config.environment },
      );
    }
    if (stage === "web-build") return nodeTask("build:web");
    if (stage === "worker") {
      return processManager.start(
        UV,
        ["run", "--package", "cairn-worker", "cairn-worker", "serve"],
        { env: config.environment },
      );
    }
    if (stage === "production") {
      const buildCode = await processManager.run(
        process.execPath,
        ["apps/web/scripts/verify-production-build.mjs"],
        { env: config.environment },
      );
      if (buildCode !== 0) return buildCode;
      return processManager.run(
        process.execPath,
        ["scripts/verify-auth-proxy.mjs"],
        { env: config.environment },
      );
    }
    if (stage === "browser") {
      return processManager.run(
        process.execPath,
        ["apps/web/scripts/verify-web.mjs"],
        { env: config.environment },
      );
    }
    throw new Error(`Unknown core verification stage: ${stage}`);
  };
}

export function createShutdownController({
  processManager,
  compose,
  projectName,
  reportError = console.error,
}) {
  let resolveTermination;
  let requested = false;
  let shutdownPromise;
  const termination = new Promise((resolvePromise) => {
    resolveTermination = resolvePromise;
  });

  return {
    termination,
    request(signal) {
      if (requested) return;
      requested = true;
      resolveTermination({ requested: true, signal });
    },
    shutdown(api, cleanupCompose = true) {
      shutdownPromise ??= (async () => {
        let exitCode = 0;
        if (api !== null) {
          try {
            await api.stop();
          } catch (error) {
            reportError(`Failed to stop verification API: ${String(error)}`);
            exitCode = 1;
          }
        }
        try {
          await processManager.stopAll();
        } catch (error) {
          reportError(`Failed to stop verification children: ${String(error)}`);
          exitCode = 1;
        }
        if (cleanupCompose) {
          try {
            const cleanupCode = await compose([
              "-p",
              projectName,
              "down",
              "--volumes",
              "--remove-orphans",
            ]);
            if (cleanupCode !== 0) exitCode = cleanupCode;
          } catch (error) {
            reportError(`Failed to clean verification Compose project: ${String(error)}`);
            exitCode = 1;
          }
        }
        return exitCode;
      })();
      return shutdownPromise;
    },
  };
}

async function waitForManagedService(service, managed, readyUrl, waitForUrl, termination) {
  const result = await Promise.race([
    waitForUrl(readyUrl).then(() => ({ ready: true })),
    ...managed.map((candidate) => candidate.process.completion.then((completion) => ({
      ready: false,
      exited: candidate.name,
      completion,
    }))),
    termination,
  ]);
  if (result?.requested === true) return false;
  if (!result.ready) {
    throw new Error(
      `Verification ${result.exited ?? service.name} exited before ${service.name} readiness `
      + `(code=${result.completion.code}, signal=${result.completion.signal})`,
    );
  }
  return true;
}

export async function runCoreVerification(options = {}) {
  const config = resolveVerificationConfig(options.environment, {
    projectName: options.projectName,
  });
  const processManager = options.processManager ?? createProcessManager();
  const compose = options.compose ?? createCompose(config, processManager);
  const startCompose = options.startCompose ?? compose.start ?? (async (args) => ({
    completion: compose(args).then((code) => ({ code, signal: null })),
    stop: async () => undefined,
  }));
  const run = options.run ?? createStageRunner(config, processManager);
  const waitForUrl = options.waitForUrl ?? waitForServer;
  const reportError = options.reportError ?? console.error;
  const shutdown = options.shutdown ?? createShutdownController({
    processManager,
    compose,
    projectName: config.projectName,
    reportError,
  });
  const termination = options.termination ?? shutdown.termination ?? NEVER;
  const signals = options.handleSignals ? installSignalHandlers(shutdown) : null;
  let api = null;
  const managed = [];
  let composeStarted = false;
  let exitCode = 0;

  try {
    const startupAbort = new AbortController();
    const startupPromise = startCompose([
      "-p",
      config.projectName,
      "up",
      "-d",
      "--build",
      "--wait",
      "postgres",
      "minio",
    ], { signal: startupAbort.signal });
    const startup = await Promise.race([
      startupPromise.then((process) => ({ process })),
      termination,
    ]);
    if (startup?.requested === true) {
      startupAbort.abort();
      try {
        const lateProcess = await startupPromise;
        composeStarted = true;
        await lateProcess.stop();
      } catch {
        // Abort during Docker discovery means no Compose project was started.
      }
      exitCode = 1;
    } else {
      composeStarted = true;
      const startupResult = await Promise.race([startup.process.completion, termination]);
      if (startupResult?.requested === true) await startup.process.stop();
      exitCode = startupResult.signal === null ? (startupResult.code ?? 1) : 1;
    }
    if (exitCode === 0) {
      for (const stage of STAGES) {
        const stageResult = await Promise.race([
          run(stage, config),
          termination,
          ...managed.map((service) => service.process.completion.then((completion) => ({
            earlyExit: service.name,
            completion,
          }))),
        ]);
        if (stageResult?.requested === true) {
          exitCode = 1;
          break;
        }
        if (stageResult?.earlyExit !== undefined) {
          const completion = stageResult.completion;
          throw new Error(
            `Verification ${stageResult.earlyExit} exited early (code=${completion.code}, signal=${completion.signal})`,
          );
        }
        if (["embedding", "api", "worker"].includes(stage) && typeof stageResult === "object") {
          const service = { name: stage, process: stageResult };
          managed.push(service);
          if (stage === "api") api = stageResult;
          if (stage === "embedding") {
            if (!await waitForManagedService(
              service, managed, `${config.embeddingOrigin}/health`, waitForUrl, termination,
            )) {
              exitCode = 1;
              break;
            }
          }
          if (stage === "api") {
            if (!await waitForManagedService(
              service, managed, `${config.apiOrigin}/ready`, waitForUrl, termination,
            )) {
              exitCode = 1;
              break;
            }
          }
          continue;
        }
        exitCode = stageResult;
        if (exitCode !== 0) break;
      }
      if (exitCode === 0 && managed.length > 0) {
        const boundary = await Promise.race([
          termination,
          ...managed.map((service) => service.process.completion.then((completion) => ({
            earlyExit: service.name,
            completion,
          }))),
          new Promise((resolveBoundary) => setImmediate(() => resolveBoundary({ stable: true }))),
        ]);
        if (boundary?.requested === true || boundary?.earlyExit !== undefined) exitCode = 1;
      }
    }
  } catch (error) {
    reportError(error instanceof Error ? error.message : String(error));
    exitCode = 1;
  } finally {
    const cleanupCode = await shutdown.shutdown(api, composeStarted);
    if (cleanupCode !== 0) exitCode = cleanupCode;
    signals?.dispose();
  }

  return exitCode;
}

function installSignalHandlers(shutdown) {
  const onInterrupt = () => shutdown.request("SIGINT");
  const onTerminate = () => shutdown.request("SIGTERM");
  process.on("SIGINT", onInterrupt);
  process.on("SIGTERM", onTerminate);
  return {
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
  process.exitCode = await runCoreVerification({
    processManager,
    handleSignals: true,
  });
}

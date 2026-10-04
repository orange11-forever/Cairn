import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";

import {
  createProcessManager,
  createShutdownController,
  createStageRunner,
  createVerificationProjectName,
  resolveVerificationConfig,
  runCoreVerification,
} from "../../../../scripts/verify-core.mjs";

function deferred() {
  let resolve;
  const promise = new Promise((next) => { resolve = next; });
  return { promise, resolve };
}

test("MinIO verification stage invokes the daemon-backed smoke", async () => {
  const calls = [];
  const runner = createStageRunner(
    { environment: { CAIRN_ENVIRONMENT: "test" } },
    {
      run: async (command, args, options) => {
        calls.push({ command, args, options });
        return 0;
      },
    },
  );

  assert.equal(await runner("minio"), 0);
  assert.deepEqual(calls, [
    {
      command: process.execPath,
      args: ["scripts/minio-smoke.mjs"],
      options: { env: { CAIRN_ENVIRONMENT: "test" } },
    },
  ]);
});

test("verification project names use only the repository prefix and random hex", () => {
  const projectName = createVerificationProjectName({
    pid: 4321,
    randomBytes: () => Buffer.from("a1b2c3d4", "hex"),
  });

  assert.equal(projectName, "cairn-verify-4321-a1b2c3d4");
  assert.match(projectName, /^cairn-verify-[0-9]+-[0-9a-f]{8}$/);
});

test("verification database and service ports are configurable", () => {
  const config = resolveVerificationConfig({
    CAIRN_VERIFY_POSTGRES_PORT: "55499",
    CAIRN_VERIFY_MINIO_PORT: "59099",
    CAIRN_VERIFY_MINIO_CONSOLE_PORT: "59199",
    CAIRN_VERIFY_API_PORT: "58099",
    CAIRN_VERIFY_EMBEDDING_PORT: "58199",
    CAIRN_VERIFY_WEB_PORT: "55099",
    CAIRN_VERIFY_PROXY_PORT: "58499",
  }, { projectName: "cairn-verify-fixed-deadbeef" });

  assert.equal(config.projectName, "cairn-verify-fixed-deadbeef");
  assert.equal(config.databasePort, 55499);
  assert.equal(config.minioPort, 59099);
  assert.equal(config.environment.CAIRN_OBJECT_STORE_ENDPOINT_URL, "http://127.0.0.1:59099");
  assert.equal(config.environment.CAIRN_TEST_S3_ENDPOINT_URL, "http://127.0.0.1:59099");
  assert.equal(config.apiOrigin, "http://localhost:58099");
  assert.equal(config.embeddingOrigin, "http://127.0.0.1:58199");
  assert.equal(config.webOrigin, "http://localhost:55099");
  assert.equal(config.mockOrigin, undefined);
  assert.equal(config.environment.CAIRN_VERIFY_MOCK_PORT, undefined);
  assert.equal(config.environment.VITE_MOCK_API_URL, undefined);
  assert.equal(config.environment.EMBEDDING_BASE_URL, "http://127.0.0.1:58199/v1");
  assert.equal(config.environment.EMBEDDING_PROVIDER, "local-fake");
  assert.equal(config.environment.EMBEDDING_DIM, "1024");
  assert.equal(config.environment.CAIRN_OBJECT_STORE_BUCKET, "cairn-test");
  assert.match(config.databaseUrl, /127\.0\.0\.1:55499\/cairn_test$/);
});

test("offline verification excludes real Feishu credentials and selects guarded fixture Worker", async () => {
  const config = resolveVerificationConfig({
    CAIRN_FEISHU_CREDENTIALS_JSON: '{"private":"secret"}',
    FEISHU_TEST_APP_SECRET: "private-secret",
    CAIRN_VERIFY_FEISHU_REUSE_SOURCE: "1",
    CAIRN_VERIFY_REUSE_WEB: "1",
  }, { projectName: "cairn-verify-feishu-deadbeef" });
  assert.equal(config.environment.CAIRN_FEISHU_CREDENTIALS_JSON, "{}");
  assert.equal(config.environment.FEISHU_TEST_APP_SECRET, undefined);
  assert.equal(config.environment.CAIRN_VERIFY_FEISHU_REUSE_SOURCE, undefined);
  assert.equal(config.environment.CAIRN_VERIFY_REUSE_WEB, undefined);
  assert.equal(config.productionEnvironment.FEISHU_TEST_APP_SECRET, undefined);
  assert.equal(config.environment.CAIRN_VERIFY_FAKE_FEISHU, "1");
  const calls = [];
  const runner = createStageRunner(config, {
    start: (command, args, options) => {
      calls.push({ command, args, options });
      return { completion: new Promise(() => undefined), stop: async () => undefined };
    },
  });
  await runner("worker");
  assert.deepEqual(calls[0].args, [
    "run", "--package", "cairn-worker", "python",
    "apps/worker/tests/support/verify_feishu_worker.py",
  ]);
  assert.equal(calls[0].options.env.CAIRN_VERIFY_FAKE_FEISHU, "1");
});

test("core process manager bridges Compose variables when WSL launches docker.exe", async () => {
  let childEnvironment;
  const processManager = createProcessManager({
    platform: "linux",
    spawnProcess: (_command, _args, options) => {
      childEnvironment = options.env;
      const child = new EventEmitter();
      queueMicrotask(() => child.emit("exit", 0, null));
      return child;
    },
  });

  const exitCode = await processManager.run("docker.exe", ["compose", "config"], {
    env: {
      CAIRN_POSTGRES_PORT: "55436",
      POSTGRES_DB: "cairn_test",
      POSTGRES_PASSWORD: "cairn-local-only",
      POSTGRES_USER: "cairn",
    },
  });

  assert.equal(exitCode, 0);
  assert.equal(
    childEnvironment.WSLENV,
    "CAIRN_POSTGRES_PORT:POSTGRES_DB:POSTGRES_USER:POSTGRES_PASSWORD",
  );
});

test("core verification always removes its isolated Compose project", async () => {
  const calls = [];
  const exitCode = await runCoreVerification({
    projectName: "cairn-test-fixed",
    compose: async (args) => {
      calls.push(args);
      return 0;
    },
    run: async (name) => name === "browser" ? 1 : 0,
    reportError: () => undefined,
  });

  assert.equal(exitCode, 1);
  assert.deepEqual(calls.at(-1), [
    "-p",
    "cairn-test-fixed",
    "down",
    "--volumes",
    "--remove-orphans",
  ]);
  assert.equal(calls.some((args) => args.includes("compose")), false);
});

test("successful verification follows the required stage order", async () => {
  const stages = [];
  const composeCalls = [];
  const exitCode = await runCoreVerification({
    projectName: "cairn-test-order",
    compose: async (args) => {
      composeCalls.push(args);
      return 0;
    },
    run: async (name) => {
      stages.push(name);
      return 0;
    },
    reportError: () => undefined,
  });

  assert.equal(exitCode, 0);
  assert.deepEqual(composeCalls[0], [
    "-p",
    "cairn-test-order",
    "up",
    "-d",
    "--build",
    "--wait",
    "postgres",
    "minio",
  ]);
  assert.deepEqual(stages, [
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
  assert.deepEqual(composeCalls.at(-1), [
    "-p",
    "cairn-test-order",
    "down",
    "--volumes",
    "--remove-orphans",
  ]);
});

test("Compose startup failure still cleans only the requested verification project", async () => {
  const calls = [];
  const exitCode = await runCoreVerification({
    projectName: "cairn-test-startup-failure",
    compose: async (args) => {
      calls.push(args);
      return args.includes("up") ? 1 : 0;
    },
    run: async () => {
      throw new Error("stages must not start");
    },
    reportError: () => undefined,
  });

  assert.equal(exitCode, 1);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls.at(-1), [
    "-p",
    "cairn-test-startup-failure",
    "down",
    "--volumes",
    "--remove-orphans",
  ]);
});

test("default development Compose project is rejected before Docker is called", async () => {
  const calls = [];

  await assert.rejects(
    runCoreVerification({
      projectName: "compose",
      compose: async (args) => {
        calls.push(args);
        return 0;
      },
      run: async () => 0,
      reportError: () => undefined,
    }),
    /verification project must match/,
  );
  assert.deepEqual(calls, []);
});

test("repeated signals await one child shutdown and isolated Compose cleanup", async () => {
  const events = [];
  let releaseChildren;
  const childrenStopped = new Promise((resolve) => {
    releaseChildren = resolve;
  });
  const processManager = {
    stopAll: async () => {
      events.push("stop-children");
      await childrenStopped;
      events.push("children-stopped");
    },
  };
  const compose = async (args) => {
    events.push(args.includes("down") ? "compose-down" : "compose-up");
    return 0;
  };
  const shutdown = createShutdownController({
    processManager,
    compose,
    projectName: "cairn-test-interrupted",
    reportError: () => undefined,
  });
  let verificationSettled = false;
  const verification = runCoreVerification({
    projectName: "cairn-test-interrupted",
    processManager,
    compose,
    run: async () => new Promise(() => undefined),
    shutdown,
    reportError: () => undefined,
  }).finally(() => {
    verificationSettled = true;
  });

  await new Promise((resolve) => setImmediate(resolve));
  shutdown.request("SIGTERM");
  shutdown.request("SIGINT");
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(verificationSettled, false);
  assert.deepEqual(events, ["compose-up", "stop-children"]);
  releaseChildren();
  assert.equal(await verification, 1);
  assert.equal(await shutdown.shutdown(null), 0);
  assert.deepEqual(events, [
    "compose-up",
    "stop-children",
    "children-stopped",
    "compose-down",
  ]);
});

test("shutdown still removes the Compose project when child shutdown throws", async () => {
  const events = [];
  const errors = [];
  const shutdown = createShutdownController({
    processManager: {
      stopAll: async () => {
        events.push("stop-children");
        throw new Error("child stop failed");
      },
    },
    compose: async (args) => {
      events.push(args.includes("down") ? "compose-down" : "unexpected-compose");
      return 0;
    },
    projectName: "cairn-test-cleanup-error",
    reportError: (message) => errors.push(message),
  });

  assert.equal(await shutdown.shutdown(null), 1);
  assert.deepEqual(events, ["stop-children", "compose-down"]);
  assert.deepEqual(errors, ["Failed to stop verification children: Error: child stop failed"]);
});

test("fake Embedding readiness and Worker early exit fail verification", async () => {
  for (const failingService of ["embedding", "worker"]) {
    const failure = deferred();
    const verification = runCoreVerification({
      projectName: `cairn-test-${failingService}-exit`,
      compose: async () => 0,
      run: async (stage) => {
        if (stage === failingService) {
          queueMicrotask(() => failure.resolve({ code: 0, signal: null }));
          return { completion: failure.promise, stop: async () => undefined };
        }
        if (stage === "web-build" && failingService === "worker") {
          return new Promise(() => undefined);
        }
        return 0;
      },
      waitForUrl: async (url) => {
        if (failingService === "embedding" && url.endsWith("/health")) {
          return new Promise(() => undefined);
        }
      },
      reportError: () => undefined,
    });
    assert.equal(await verification, 1, failingService);
  }
});

test("termination interrupts managed readiness and still cleans Compose", async () => {
  const stop = deferred();
  const composeCalls = [];
  const verification = runCoreVerification({
    projectName: "cairn-test-readiness-signal",
    compose: async (args) => { composeCalls.push(args); return 0; },
    run: async (stage) => {
      if (stage !== "embedding") return 0;
      queueMicrotask(() => stop.resolve({ requested: true, signal: "SIGTERM" }));
      return { completion: new Promise(() => undefined), stop: async () => undefined };
    },
    waitForUrl: async () => new Promise(() => undefined),
    termination: stop.promise,
    reportError: () => undefined,
  });
  assert.equal(await verification, 1);
  assert.deepEqual(composeCalls.at(-1), [
    "-p", "cairn-test-readiness-signal", "down", "--volumes", "--remove-orphans",
  ]);
});

test("managed exit after the final stage cannot be reported as success", async () => {
  const workerExit = deferred();
  const never = new Promise(() => undefined);
  const exitCode = await runCoreVerification({
    projectName: "cairn-test-final-boundary",
    compose: async () => 0,
    run: async (stage) => {
      if (stage === "embedding" || stage === "api") {
        return { completion: never, stop: async () => undefined };
      }
      if (stage === "worker") {
        return { completion: workerExit.promise, stop: async () => undefined };
      }
      if (stage === "production") {
        setImmediate(() => workerExit.resolve({ code: 0, signal: null }));
      }
      return 0;
    },
    waitForUrl: async () => undefined,
    reportError: () => undefined,
  });
  assert.equal(exitCode, 1);
});

test("termination stops a late Compose startup before isolated cleanup", async () => {
  const stop = deferred();
  const composeCalls = [];
  let startupStops = 0;
  const verification = runCoreVerification({
    projectName: "cairn-test-compose-signal",
    compose: async (args) => { composeCalls.push(args); return 0; },
    startCompose: async () => {
      queueMicrotask(() => stop.resolve({ requested: true, signal: "SIGTERM" }));
      return {
        completion: new Promise(() => undefined),
        stop: async () => { startupStops += 1; },
      };
    },
    termination: stop.promise,
    reportError: () => undefined,
  });
  assert.equal(await verification, 1);
  assert.equal(startupStops, 1);
  assert.deepEqual(composeCalls, [[
    "-p", "cairn-test-compose-signal", "down", "--volumes", "--remove-orphans",
  ]]);
});

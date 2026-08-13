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
    CAIRN_VERIFY_WEB_PORT: "55099",
    CAIRN_VERIFY_MOCK_PORT: "58799",
  }, { projectName: "cairn-verify-fixed-deadbeef" });

  assert.equal(config.projectName, "cairn-verify-fixed-deadbeef");
  assert.equal(config.databasePort, 55499);
  assert.equal(config.minioPort, 59099);
  assert.equal(config.environment.CAIRN_OBJECT_STORE_ENDPOINT_URL, "http://127.0.0.1:59099");
  assert.equal(config.environment.CAIRN_TEST_S3_ENDPOINT_URL, "http://127.0.0.1:59099");
  assert.equal(config.apiOrigin, "http://localhost:58099");
  assert.equal(config.webOrigin, "http://localhost:55099");
  assert.equal(config.mockOrigin, "http://localhost:58799");
  assert.match(config.databaseUrl, /127\.0\.0\.1:55499\/cairn_test$/);
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
  assert.deepEqual(stages.slice(0, 2), ["object-store-bootstrap", "minio"]);
  assert.deepEqual(stages, [
    "object-store-bootstrap",
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

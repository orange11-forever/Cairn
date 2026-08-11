import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";

import {
  createProcessManager,
  createVerificationProjectName,
  resolveVerificationConfig,
  runCoreVerification,
} from "../../../../scripts/verify-core.mjs";

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
    CAIRN_VERIFY_API_PORT: "58099",
    CAIRN_VERIFY_WEB_PORT: "55099",
    CAIRN_VERIFY_MOCK_PORT: "58799",
  }, { projectName: "cairn-verify-fixed-deadbeef" });

  assert.equal(config.projectName, "cairn-verify-fixed-deadbeef");
  assert.equal(config.databasePort, 55499);
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
    "--wait",
    "postgres",
  ]);
  assert.deepEqual(stages, [
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

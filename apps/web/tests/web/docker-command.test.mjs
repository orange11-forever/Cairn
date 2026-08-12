import assert from "node:assert/strict";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { resolveDockerCommand, runCompose } from "../../../../scripts/docker-command.mjs";
import { runInfra } from "../../../../scripts/infra.mjs";

test("falls back to docker.exe when the WSL docker shim cannot reach an engine", async () => {
  const attempts = [];
  const command = await resolveDockerCommand({
    platform: "linux",
    env: {},
    probe: async (candidate) => {
      attempts.push(candidate);
      return candidate === "docker.exe";
    },
  });
  assert.equal(command, "docker.exe");
  assert.deepEqual(attempts, ["docker", "docker.exe"]);
});

test("honors an explicit CAIRN_DOCKER_COMMAND before platform defaults", async () => {
  const command = await resolveDockerCommand({
    platform: "linux",
    env: { CAIRN_DOCKER_COMMAND: "/opt/docker-client" },
    probe: async (candidate) => candidate === "/opt/docker-client",
  });
  assert.equal(command, "/opt/docker-client");
});

test("bridges Compose interpolation variables to docker.exe from WSL", async (context) => {
  const temporaryDirectory = await mkdtemp(join(tmpdir(), "cairn-docker-env-"));
  context.after(() => rm(temporaryDirectory, { recursive: true }));
  const dockerCommand = join(temporaryDirectory, "docker.exe");
  const outputPath = join(temporaryDirectory, "wslenv.txt");
  await writeFile(
    dockerCommand,
    [
      "#!/usr/bin/env node",
      'const { writeFileSync } = require("node:fs");',
      'writeFileSync(process.env.CAIRN_DOCKER_ENV_OUTPUT, process.env.WSLENV ?? "", "utf8");',
    ].join("\n"),
  );
  await chmod(dockerCommand, 0o755);

  const exitCode = await runCompose({
    dockerCommand,
    args: ["config"],
    env: {
      CAIRN_DOCKER_ENV_OUTPUT: outputPath,
      CAIRN_POSTGRES_PORT: "55436",
      CORS_ORIGINS: "https://web.test",
      HTTP_PROXY: "http://127.0.0.1:7897",
      HTTPS_PROXY: "http://localhost:7897",
      PATH: process.env.PATH,
      POSTGRES_DB: "cairn_test",
      POSTGRES_PASSWORD: "cairn-local-only",
      POSTGRES_USER: "cairn",
      WSLENV: "EXISTING/p:POSTGRES_DB/w",
    },
    platform: "linux",
    stdio: "ignore",
  });

  assert.equal(exitCode, 0);
  assert.equal(
    await readFile(outputPath, "utf8"),
    "EXISTING/p:POSTGRES_DB/w:CAIRN_POSTGRES_PORT:POSTGRES_USER:POSTGRES_PASSWORD:" +
      "CORS_ORIGINS:CAIRN_BUILD_HTTP_PROXY:CAIRN_BUILD_HTTPS_PROXY",
  );
});

test("infra up waits for PostgreSQL and MinIO before bootstrapping the bucket", async () => {
  const calls = [];
  const exitCode = await runInfra("up", [], { PATH: process.env.PATH }, {
    resolveDocker: async () => "docker.exe",
    compose: async (options) => {
      calls.push({ kind: "compose", options });
      return 0;
    },
    bootstrap: async (environment) => {
      calls.push({ kind: "bootstrap", environment });
      return 0;
    },
  });

  assert.equal(exitCode, 0);
  assert.deepEqual(calls.map((call) => call.kind), ["compose", "bootstrap"]);
  assert.deepEqual(calls[0].options.args.slice(2), [
    "up",
    "-d",
    "--build",
    "--wait",
    "postgres",
    "minio",
  ]);
});

test("infra up stops before bootstrap when Compose startup fails", async () => {
  let bootstrapped = false;
  const exitCode = await runInfra("up", [], {}, {
    resolveDocker: async () => "docker.exe",
    compose: async () => 1,
    bootstrap: async () => {
      bootstrapped = true;
      return 0;
    },
  });

  assert.equal(exitCode, 1);
  assert.equal(bootstrapped, false);
});

import assert from "node:assert/strict";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { resolveDockerCommand, runCompose } from "../../../../scripts/docker-command.mjs";

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
      ...process.env,
      CAIRN_DOCKER_ENV_OUTPUT: outputPath,
      CAIRN_POSTGRES_PORT: "55436",
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
    "EXISTING/p:POSTGRES_DB/w:CAIRN_POSTGRES_PORT:POSTGRES_USER:POSTGRES_PASSWORD",
  );
});

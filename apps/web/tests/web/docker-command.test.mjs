import assert from "node:assert/strict";
import test from "node:test";

import { resolveDockerCommand } from "../../../../scripts/docker-command.mjs";

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

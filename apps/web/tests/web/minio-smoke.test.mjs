import assert from "node:assert/strict";
import test from "node:test";

import {
  MINIO_RELEASE,
  runMinioSmoke,
} from "../../../../scripts/minio-smoke.mjs";

function commandResult(stdout = "") {
  return { stdout, stderr: "" };
}

test("MinIO smoke builds a fresh project and verifies version plus object I/O", async () => {
  const calls = [];
  const runCommand = async (command, args, options) => {
    calls.push({ command, args, options });
    if (args.includes("--version")) {
      return commandResult(`minio version ${MINIO_RELEASE} (commit-id=9e49d5e)\n`);
    }
    if (args.includes("port")) return commandResult("127.0.0.1:49152\n");
    return commandResult();
  };

  await runMinioSmoke({
    projectName: "cairn-minio-smoke-unit",
    environment: { PATH: "/bin" },
    runCommand,
  });

  assert.deepEqual(calls[0].args.slice(-5), ["up", "-d", "--build", "--wait", "minio"]);
  assert.equal(calls[0].options.env.CAIRN_MINIO_PORT, "0");
  assert.equal(calls[0].options.env.CAIRN_OBJECT_STORE_ACCESS_KEY, "cairn-smoke-access");
  assert.ok(calls.some(({ args }) => args.includes("--version")));

  const objectSmoke = calls.find(({ args }) => args.includes("scripts/minio-object-smoke.py"));
  assert.deepEqual(objectSmoke.args, [
    "run",
    "--package",
    "cairn-api",
    "python",
    "scripts/minio-object-smoke.py",
    "http://127.0.0.1:49152",
  ]);
  assert.equal(objectSmoke.options.env.CAIRN_OBJECT_STORE_ACCESS_KEY, "cairn-smoke-access");

  assert.deepEqual(calls.at(-1).args.slice(-3), [
    "down",
    "--volumes",
    "--remove-orphans",
  ]);
  assert.ok(
    calls
      .filter(({ command }) => command === "docker")
      .every(({ args }) => args.includes("cairn-minio-smoke-unit")),
  );
});

test("MinIO smoke bridges WSL proxy trust into docker.exe builds", async () => {
  const calls = [];
  const runCommand = async (command, args, options) => {
    calls.push({ command, args, options });
    if (args.includes("--version")) return commandResult(`minio version ${MINIO_RELEASE}\n`);
    if (args.includes("port")) return commandResult("127.0.0.1:49154\n");
    return commandResult();
  };

  await runMinioSmoke({
    projectName: "cairn-minio-smoke-proxy",
    dockerCommand: "docker.exe",
    platform: "linux",
    environment: {
      CAIRN_BUILD_CA_CERT_BASE64: "Y2VydA==",
      HTTP_PROXY: "http://127.0.0.1:7897",
      HTTPS_PROXY: "http://localhost:7897",
      NO_PROXY: "localhost,127.0.0.1",
    },
    runCommand,
  });

  const dockerEnvironment = calls.find(({ command }) => command === "docker.exe").options.env;
  assert.equal(dockerEnvironment.CAIRN_BUILD_HTTP_PROXY, "http://host.docker.internal:7897/");
  assert.equal(dockerEnvironment.CAIRN_BUILD_HTTPS_PROXY, "http://host.docker.internal:7897/");
  assert.equal(
    dockerEnvironment.WSLENV,
    "CAIRN_MINIO_PORT:CAIRN_MINIO_CONSOLE_PORT:CAIRN_OBJECT_STORE_ACCESS_KEY:" +
      "CAIRN_OBJECT_STORE_SECRET_KEY:CAIRN_BUILD_HTTP_PROXY:CAIRN_BUILD_HTTPS_PROXY:" +
      "NO_PROXY:CAIRN_BUILD_CA_CERT_BASE64",
  );
});

test("MinIO smoke removes only its isolated project after a failed object round trip", async () => {
  const calls = [];
  const runCommand = async (command, args, options) => {
    calls.push({ command, args, options });
    if (args.includes("--version")) return commandResult(`minio version ${MINIO_RELEASE}\n`);
    if (args.includes("port")) return commandResult("0.0.0.0:49153\n");
    if (args.includes("scripts/minio-object-smoke.py")) throw new Error("object smoke failed");
    return commandResult();
  };

  await assert.rejects(
    runMinioSmoke({
      projectName: "cairn-minio-smoke-cleanup",
      runCommand,
    }),
    /object smoke failed/,
  );

  assert.deepEqual(calls.at(-1).args.slice(-3), [
    "down",
    "--volumes",
    "--remove-orphans",
  ]);
  assert.ok(
    calls
      .filter(({ command }) => command === "docker")
      .every(({ args }) => args.includes("cairn-minio-smoke-cleanup")),
  );
});

test("MinIO smoke rejects a binary with development version metadata and cleans up", async () => {
  const calls = [];
  const runCommand = async (command, args, options) => {
    calls.push({ command, args, options });
    if (args.includes("--version")) return commandResult("minio version DEVELOPMENT.GOGET\n");
    return commandResult();
  };

  await assert.rejects(
    runMinioSmoke({
      projectName: "cairn-minio-smoke-version",
      runCommand,
    }),
    /expected MinIO release/,
  );

  assert.deepEqual(calls.at(-1).args.slice(-3), [
    "down",
    "--volumes",
    "--remove-orphans",
  ]);
});

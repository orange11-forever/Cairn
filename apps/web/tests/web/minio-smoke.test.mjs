import assert from "node:assert/strict";
import test from "node:test";

import {
  MINIO_RELEASE,
  runMinioSmokeCli,
  runMinioSmoke,
} from "../../../../scripts/minio-smoke.mjs";
import {
  DockerClientNotFoundError,
  DockerEngineUnavailableError,
} from "../../../../scripts/docker-command.mjs";

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

for (const version of [`${MINIO_RELEASE}-suffix`, `${MINIO_RELEASE.slice(0, -1)}X`]) {
  test(`MinIO smoke rejects the near-match release token ${version}`, async () => {
    const runCommand = async (_command, args) => {
      if (args.includes("--version")) return commandResult(`minio version ${version}\n`);
      return commandResult();
    };

    await assert.rejects(
      runMinioSmoke({
        projectName: "cairn-minio-smoke-near-match",
        runCommand,
      }),
      /expected MinIO release/,
    );
  });
}

test("MinIO CLI skips only when no Docker client is installed", async () => {
  const logs = [];
  const exitCode = await runMinioSmokeCli({
    resolveDocker: async () => {
      throw new DockerClientNotFoundError(["docker", "docker.exe"]);
    },
    log: (message) => logs.push(message),
    reportError: () => assert.fail("absent client must not report a failure"),
  });

  assert.equal(exitCode, 0);
  assert.match(logs[0], /^SKIP: MinIO smoke unavailable:/);
});

for (const error of [
  new DockerEngineUnavailableError(["docker"]),
  new Error("Docker client probe failed: permission denied"),
]) {
  test(`MinIO CLI fails when Docker is present but unavailable: ${error.constructor.name}`, async () => {
    const failures = [];
    const exitCode = await runMinioSmokeCli({
      resolveDocker: async () => {
        throw error;
      },
      log: () => assert.fail("daemon/probe failure must not skip"),
      reportError: (message) => failures.push(message),
    });

    assert.equal(exitCode, 1);
    assert.deepEqual(failures, [error.message]);
  });
}

import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import {
  dockerEnvironment,
  resolveDockerCommand,
} from "../../../../scripts/docker-command.mjs";

const REPOSITORY_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");
const execFileAsync = promisify(execFile);

async function readToml(relativePath) {
  const parser = [
    "import json, pathlib, sys, tomllib",
    "path = pathlib.Path(sys.argv[1])",
    "print(json.dumps(tomllib.loads(path.read_text(encoding='utf-8'))))",
  ].join("; ");
  const { stdout } = await execFileAsync(
    "python3",
    ["-c", parser, join(REPOSITORY_ROOT, relativePath)],
    { cwd: REPOSITORY_ROOT },
  );
  return JSON.parse(stdout);
}

async function readComposeConfig() {
  const baseEnv = {
    ...process.env,
    CAIRN_BUILD_CA_CERT_BASE64: "Y2VydA==",
    CAIRN_BUILD_HTTP_PROXY: "http://proxy.example:8080",
    CAIRN_BUILD_HTTPS_PROXY: "http://proxy.example:8443",
    CAIRN_MINIO_PORT: "19000",
    CAIRN_MINIO_CONSOLE_PORT: "19001",
    NO_PROXY: "localhost,127.0.0.1",
  };
  const dockerCommand = await resolveDockerCommand({ env: baseEnv });
  const { stdout } = await execFileAsync(
    dockerCommand,
    ["compose", "-f", "deploy/compose/core.yml", "config", "--format", "json"],
    {
      cwd: REPOSITORY_ROOT,
      env: dockerEnvironment({ dockerCommand, env: baseEnv }),
    },
  );
  return JSON.parse(stdout);
}

test("Web tooling belongs to apps/web", async () => {
  const workspace = await readFile(join(REPOSITORY_ROOT, "pnpm-workspace.yaml"), "utf8");
  const root = JSON.parse(await readFile(join(REPOSITORY_ROOT, "package.json"), "utf8"));
  const web = JSON.parse(
    await readFile(join(REPOSITORY_ROOT, "apps/web/package.json"), "utf8"),
  );

  assert.match(workspace, /apps\/\*/);
  assert.match(workspace, /packages\/\*/);
  assert.deepEqual(root.dependencies ?? {}, {});
  assert.deepEqual(root.devDependencies ?? {}, {});
  assert.equal(web.scripts.test, "node scripts/run-tests.mjs");
  assert.equal(web.scripts.verify, "node scripts/run-verification.mjs");
  assert.match(web.dependencies["@tanstack/react-query"], /^5\./);
  assert.equal(web.dependencies["@cairn/contracts"], "workspace:*");
  assert.match(web.dependencies["react-router-dom"], /^7\./);

  for (const moved of ["apiError.ts", "conversations.ts", "primitives.ts", "users.ts"]) {
    await assert.rejects(
      readFile(join(REPOSITORY_ROOT, "apps/web/src/schemas", moved), "utf8"),
    );
  }

  const contracts = JSON.parse(
    await readFile(join(REPOSITORY_ROOT, "packages/contracts/package.json"), "utf8"),
  );
  assert.equal(contracts.name, "@cairn/contracts");
  assert.equal(contracts.exports["."].default, "./src/index.ts");

});

test("Python tooling resolves both API and worker package trees", async () => {
  const root = await readToml("pyproject.toml");

  assert.deepEqual(root.tool.uv.workspace.members, ["apps/api", "apps/worker"]);
  assert.deepEqual(root.tool.pytest.ini_options.testpaths, [
    "apps/api/tests",
    "apps/worker/tests",
  ]);
  assert.deepEqual(root.tool.pyright.include, [
    "apps/api/src",
    "apps/api/tests",
    "apps/worker/src",
    "apps/worker/tests",
  ]);
});

test("Core Compose resolves pgvector and healthy persistent MinIO", async () => {
  const compose = await readComposeConfig();
  const postgres = compose.services.postgres;
  const minio = compose.services.minio;

  assert.equal(postgres.image, "pgvector/pgvector:0.8.2-pg16-trixie");
  assert.ok(postgres.healthcheck.test.includes("CMD-SHELL"));
  assert.deepEqual(
    postgres.volumes.map(({ source, target }) => ({ source, target })),
    [{ source: "cairn_postgres_data", target: "/var/lib/postgresql/data" }],
  );

  const normalizedBuildContext = minio.build.context.replaceAll("\\", "/");
  assert.ok(
    normalizedBuildContext === REPOSITORY_ROOT ||
      normalizedBuildContext.endsWith(REPOSITORY_ROOT),
  );
  assert.equal(minio.build.dockerfile, "deploy/docker/minio/Dockerfile");
  assert.equal(minio.build.args.GO_VERSION, "1.24.8");
  assert.equal(minio.build.args.MINIO_VERSION, "RELEASE.2025-10-15T17-29-55Z");
  assert.equal(new URL(minio.build.args.HTTP_PROXY).origin, "http://proxy.example:8080");
  assert.equal(new URL(minio.build.args.HTTPS_PROXY).origin, "http://proxy.example:8443");
  assert.equal(minio.build.args.NO_PROXY, "localhost,127.0.0.1");
  assert.equal(minio.build.args.CAIRN_BUILD_CA_CERT_BASE64, "Y2VydA==");
  assert.deepEqual(minio.command, ["server", "/data", "--console-address", ":9001"]);
  assert.deepEqual(
    minio.ports.map(({ published, target }) => ({ published, target })),
    [
      { published: "19000", target: 9000 },
      { published: "19001", target: 9001 },
    ],
  );
  assert.deepEqual(
    minio.volumes.map(({ source, target }) => ({ source, target })),
    [{ source: "cairn_minio_data", target: "/data" }],
  );
  assert.ok(minio.healthcheck.test.includes("http://127.0.0.1:9000/minio/health/live"));
  assert.deepEqual(Object.keys(compose.volumes).sort(), [
    "cairn_minio_data",
    "cairn_postgres_data",
  ]);
});

test("MinIO source builds retain Go caches and retry transient downloads", async () => {
  const dockerfile = await readFile(
    join(REPOSITORY_ROOT, "deploy/docker/minio/Dockerfile"),
    "utf8",
  );
  assert.match(dockerfile, /--mount=type=cache,target=\/go\/pkg\/mod/);
  assert.match(dockerfile, /--mount=type=cache,target=\/root\/.cache\/go-build/);

  const temporaryRoot = await mkdtemp(join(tmpdir(), "cairn-minio-build-"));
  const fakeBin = join(temporaryRoot, "bin");
  const sourceDirectory = join(temporaryRoot, "source");
  const outputPath = join(temporaryRoot, "out", "minio");
  const invocationLog = join(temporaryRoot, "go-invocations.log");
  try {
    await mkdir(fakeBin);
    await mkdir(sourceDirectory);
    await writeFile(
      join(fakeBin, "go"),
      [
        "#!/bin/sh",
        "set -eu",
        'printf "%s\\n" "$1" >> "$CAIRN_FAKE_GO_LOG"',
        'if [ "$1" = "run" ]; then',
        "  printf '%s\\n' '-X github.com/minio/minio/cmd.Version=test'",
        "  exit 0",
        "fi",
        'attempts=$(grep -c "^build$" "$CAIRN_FAKE_GO_LOG")',
        'if [ "$attempts" -lt 3 ]; then exit 1; fi',
        ': > "$MINIO_OUTPUT_PATH"',
      ].join("\n"),
      { mode: 0o755 },
    );

    await execFileAsync(
      "sh",
      [join(REPOSITORY_ROOT, "deploy/docker/minio/build.sh")],
      {
        cwd: REPOSITORY_ROOT,
        env: {
          ...process.env,
          PATH: `${fakeBin}:${process.env.PATH}`,
          CAIRN_FAKE_GO_LOG: invocationLog,
          MINIO_BUILD_MAX_ATTEMPTS: "3",
          MINIO_BUILD_RETRY_DELAY_SECONDS: "0",
          MINIO_OUTPUT_PATH: outputPath,
          MINIO_SOURCE_DIR: sourceDirectory,
        },
      },
    );

    const invocations = (await readFile(invocationLog, "utf8")).trim().split("\n");
    assert.deepEqual(invocations, ["run", "build", "run", "build", "run", "build"]);
    assert.equal(await readFile(outputPath, "utf8"), "");
  } finally {
    await rm(temporaryRoot, { recursive: true, force: true });
  }
});

test("MinIO source builds stop at the retry limit and preserve the failure", async () => {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "cairn-minio-build-failure-"));
  const fakeBin = join(temporaryRoot, "bin");
  const sourceDirectory = join(temporaryRoot, "source");
  const outputPath = join(temporaryRoot, "out", "minio");
  const invocationLog = join(temporaryRoot, "go-invocations.log");
  try {
    await mkdir(fakeBin);
    await mkdir(sourceDirectory);
    await writeFile(
      join(fakeBin, "go"),
      [
        "#!/bin/sh",
        "set -eu",
        'printf "%s\\n" "$1" >> "$CAIRN_FAKE_GO_LOG"',
        'if [ "$1" = "run" ]; then',
        "  printf '%s\\n' '-X github.com/minio/minio/cmd.Version=test'",
        "  exit 0",
        "fi",
        "exit 37",
      ].join("\n"),
      { mode: 0o755 },
    );

    await assert.rejects(
      execFileAsync("sh", [join(REPOSITORY_ROOT, "deploy/docker/minio/build.sh")], {
        cwd: REPOSITORY_ROOT,
        env: {
          ...process.env,
          PATH: `${fakeBin}:${process.env.PATH}`,
          CAIRN_FAKE_GO_LOG: invocationLog,
          MINIO_BUILD_MAX_ATTEMPTS: "3",
          MINIO_BUILD_RETRY_DELAY_SECONDS: "0",
          MINIO_OUTPUT_PATH: outputPath,
          MINIO_SOURCE_DIR: sourceDirectory,
        },
      }),
      (error) => {
        assert.equal(error.code, 37);
        assert.equal(
          error.stderr.match(/MinIO build attempt \d+ failed; retrying/g)?.length,
          2,
        );
        return true;
      },
    );

    const invocations = (await readFile(invocationLog, "utf8")).trim().split("\n");
    assert.deepEqual(invocations, ["run", "build", "run", "build", "run", "build"]);
  } finally {
    await rm(temporaryRoot, { recursive: true, force: true });
  }
});

test("MinIO source builds reject invalid retry configuration", async () => {
  const buildScript = join(REPOSITORY_ROOT, "deploy/docker/minio/build.sh");
  const cases = [
    {
      environment: { MINIO_BUILD_MAX_ATTEMPTS: "0" },
      message: /MINIO_BUILD_MAX_ATTEMPTS must be a positive integer/,
    },
    {
      environment: { MINIO_BUILD_RETRY_DELAY_SECONDS: "-1" },
      message: /MINIO_BUILD_RETRY_DELAY_SECONDS must be a non-negative integer/,
    },
  ];

  for (const { environment, message } of cases) {
    await assert.rejects(
      execFileAsync("sh", [buildScript], {
        cwd: REPOSITORY_ROOT,
        env: { ...process.env, ...environment },
      }),
      (error) => {
        assert.equal(error.code, 2);
        assert.match(error.stderr, message);
        return true;
      },
    );
  }
});

import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

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
  const { stdout } = await execFileAsync(
    "docker",
    ["compose", "-f", "deploy/compose/core.yml", "config", "--format", "json"],
    {
      cwd: REPOSITORY_ROOT,
      env: {
        ...process.env,
        CAIRN_MINIO_PORT: "19000",
        CAIRN_MINIO_CONSOLE_PORT: "19001",
      },
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

  assert.equal(minio.build.context, REPOSITORY_ROOT);
  assert.equal(minio.build.dockerfile, "deploy/docker/minio/Dockerfile");
  assert.equal(minio.build.args.GO_VERSION, "1.24.8");
  assert.equal(minio.build.args.MINIO_VERSION, "RELEASE.2025-10-15T17-29-55Z");
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

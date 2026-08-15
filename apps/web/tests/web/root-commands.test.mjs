import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { join } from "node:path";

import { taskInvocation } from "../../../../scripts/run-task.mjs";

const REPOSITORY_ROOT = join(import.meta.dirname, "../../../..");
const APPROVED_SCRIPTS = [
  "auth:cleanup",
  "build",
  "build:api",
  "build:web",
  "check:sdk",
  "db:migrate",
  "db:seed",
  "dev:api",
  "dev:core",
  "dev:web",
  "dev:worker",
  "generate:sdk",
  "infra:up",
  "lint:api",
  "lint:worker",
  "mock:web",
  "test",
  "test:api",
  "test:contracts",
  "test:sdk",
  "test:web",
  "test:worker",
  "typecheck",
  "typecheck:api",
  "typecheck:contracts",
  "typecheck:sdk",
  "typecheck:web",
  "typecheck:worker",
  "verify",
  "verify:api",
  "verify:core",
  "verify:web",
  "worker:once",
  "worker:preflight",
];

function runNode(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, {
      cwd: REPOSITORY_ROOT,
      shell: false,
      stdio: "ignore",
    });
    child.on("error", reject);
    child.on("exit", (code, signal) => resolve(signal === null ? (code ?? 1) : 1));
  });
}

test("root commands are allowlisted and shell neutral", async () => {
  const root = JSON.parse(await readFile(join(REPOSITORY_ROOT, "package.json"), "utf8"));
  const scriptNames = Object.keys(root.scripts).sort();

  assert.deepEqual(scriptNames, APPROVED_SCRIPTS);
  assert.equal(root.scripts["dev:api"], "node scripts/run-task.mjs dev:api");
  assert.equal(root.scripts["dev:core"], "node scripts/run-task.mjs dev:core");
  assert.equal(root.scripts["test:api"], "node scripts/run-task.mjs test:api");
  assert.equal(root.scripts["typecheck:api"], "node scripts/run-task.mjs typecheck:api");
  assert.equal(root.scripts["build:api"], "node scripts/run-task.mjs build:api");
  assert.equal(root.scripts["lint:api"], "node scripts/run-task.mjs lint:api");
  assert.equal(root.scripts["db:migrate"], "node scripts/run-task.mjs db:migrate");
  assert.equal(root.scripts["db:seed"], "node scripts/run-task.mjs db:seed");
  assert.equal(root.scripts["auth:cleanup"], "node scripts/run-task.mjs auth:cleanup");
  assert.equal(root.scripts["dev:worker"], "node scripts/run-task.mjs dev:worker");
  assert.equal(root.scripts["worker:once"], "node scripts/run-task.mjs worker:once");
  assert.equal(root.scripts["worker:preflight"], "node scripts/run-task.mjs worker:preflight");
  assert.equal(root.scripts["test:worker"], "node scripts/run-task.mjs test:worker");
  assert.equal(root.scripts["lint:worker"], "node scripts/run-task.mjs lint:worker");
  assert.equal(root.scripts["typecheck:worker"], "node scripts/run-task.mjs typecheck:worker");
  assert.equal(root.scripts["generate:sdk"], "node scripts/run-task.mjs generate:sdk");
  assert.equal(root.scripts["check:sdk"], "node scripts/run-task.mjs check:sdk");
  assert.equal(root.scripts["test:sdk"], "node scripts/run-task.mjs test:sdk");
  assert.equal(root.scripts["typecheck:sdk"], "node scripts/run-task.mjs typecheck:sdk");
  assert.equal(root.scripts["verify:core"], "node scripts/run-task.mjs verify:core");
  assert.equal(
    root.scripts.test,
    "node scripts/run-tasks.mjs test:contracts test:sdk test:web test:api test:worker",
  );
  assert.equal(
    root.scripts.typecheck,
    "node scripts/run-tasks.mjs typecheck:contracts typecheck:sdk typecheck:web typecheck:api typecheck:worker",
  );
  assert.equal(
    root.scripts.verify,
    "node scripts/run-tasks.mjs test:contracts typecheck:contracts test:sdk typecheck:sdk check:sdk test:web typecheck:web test:api lint:api typecheck:api build:api test:worker lint:worker typecheck:worker verify:core",
  );

  for (const [name, command] of Object.entries(root.scripts)) {
    assert.doesNotMatch(command, /(?:^|\s)(?:cd|export)(?:\s|$)/, `${name} uses a shell builtin`);
    assert.doesNotMatch(command, /&&|\$\{|\bshell\b/, `${name} uses shell syntax`);
  }
});

test("worker tasks use exact uv package invocations", () => {
  assert.deepEqual(taskInvocation("dev:worker", "linux"), [
    "uv",
    ["run", "--package", "cairn-worker", "cairn-worker", "serve"],
  ]);
  assert.deepEqual(taskInvocation("worker:once", "linux"), [
    "uv",
    ["run", "--package", "cairn-worker", "cairn-worker", "--once"],
  ]);
  assert.deepEqual(taskInvocation("worker:preflight", "win32"), [
    "uv.exe",
    ["run", "--package", "cairn-worker", "cairn-worker", "preflight"],
  ]);
  assert.deepEqual(taskInvocation("test:worker", "linux"), [
    "uv",
    ["run", "--package", "cairn-worker", "pytest", "apps/worker/tests", "-q"],
  ]);
  assert.deepEqual(taskInvocation("lint:worker", "linux"), [
    "uv",
    ["run", "--package", "cairn-worker", "ruff", "check", "apps/worker/src", "apps/worker/tests"],
  ]);
  assert.deepEqual(taskInvocation("typecheck:worker", "linux"), [
    "uv",
    ["run", "--package", "cairn-worker", "pyright"],
  ]);
});

test("task runner rejects unknown tasks", async () => {
  const exitCode = await runNode(["scripts/run-task.mjs", "unknown:task"]);

  assert.equal(exitCode, 2);
});

test("test-down rejects unguarded project names before Docker is called", async () => {
  const exitCode = await runNode(["scripts/infra.mjs", "test-down", "--project", "cairn"]);

  assert.equal(exitCode, 2);
});

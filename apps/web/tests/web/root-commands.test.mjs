import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { join } from "node:path";

const REPOSITORY_ROOT = join(import.meta.dirname, "../../../..");
const APPROVED_SCRIPTS = [
  "build",
  "build:api",
  "build:web",
  "check:sdk",
  "db:migrate",
  "db:seed",
  "dev:api",
  "dev:core",
  "dev:web",
  "generate:sdk",
  "infra:up",
  "lint:api",
  "mock:web",
  "test",
  "test:api",
  "test:contracts",
  "test:sdk",
  "test:web",
  "typecheck",
  "typecheck:api",
  "typecheck:contracts",
  "typecheck:sdk",
  "typecheck:web",
  "verify",
  "verify:api",
  "verify:core",
  "verify:web",
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
  assert.equal(root.scripts["generate:sdk"], "node scripts/run-task.mjs generate:sdk");
  assert.equal(root.scripts["check:sdk"], "node scripts/run-task.mjs check:sdk");
  assert.equal(root.scripts["test:sdk"], "node scripts/run-task.mjs test:sdk");
  assert.equal(root.scripts["typecheck:sdk"], "node scripts/run-task.mjs typecheck:sdk");
  assert.equal(root.scripts["verify:core"], "node scripts/run-task.mjs verify:core");
  assert.equal(
    root.scripts.test,
    "node scripts/run-tasks.mjs test:contracts test:sdk test:web test:api",
  );
  assert.equal(
    root.scripts.typecheck,
    "node scripts/run-tasks.mjs typecheck:contracts typecheck:sdk typecheck:web typecheck:api",
  );
  assert.equal(
    root.scripts.verify,
    "node scripts/run-tasks.mjs test:contracts typecheck:contracts test:sdk typecheck:sdk check:sdk test:web typecheck:web test:api lint:api typecheck:api build:api verify:core",
  );

  for (const [name, command] of Object.entries(root.scripts)) {
    assert.doesNotMatch(command, /(?:^|\s)(?:cd|export)(?:\s|$)/, `${name} uses a shell builtin`);
    assert.doesNotMatch(command, /&&|\$\{|\bshell\b/, `${name} uses shell syntax`);
  }
});

test("task runner rejects unknown tasks", async () => {
  const exitCode = await runNode(["scripts/run-task.mjs", "unknown:task"]);

  assert.equal(exitCode, 2);
});

test("test-down rejects unguarded project names before Docker is called", async () => {
  const exitCode = await runNode(["scripts/infra.mjs", "test-down", "--project", "cairn"]);

  assert.equal(exitCode, 2);
});

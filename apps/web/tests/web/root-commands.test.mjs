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
  "dev:api",
  "dev:web",
  "mock:web",
  "test",
  "test:api",
  "test:web",
  "typecheck",
  "typecheck:api",
  "typecheck:web",
  "verify",
  "verify:api",
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
  assert.equal(root.scripts["test:api"], "node scripts/run-task.mjs test:api");
  assert.equal(root.scripts["typecheck:api"], "node scripts/run-task.mjs typecheck:api");
  assert.equal(root.scripts["build:api"], "node scripts/run-task.mjs build:api");
  assert.equal(
    root.scripts.verify,
    "node scripts/run-tasks.mjs test:web typecheck:web verify:web test:api lint:api typecheck:api build:api",
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

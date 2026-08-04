import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import test from "node:test";
import { join } from "node:path";

const REPOSITORY_ROOT = join(import.meta.dirname, "../../../..");

test("committed SDK artifacts match FastAPI OpenAPI", async () => {
  const exitCode = await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ["scripts/generate-sdk.mjs", "--check"], {
      cwd: REPOSITORY_ROOT,
      shell: false,
      stdio: "ignore",
    });
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve(signal === null ? (code ?? 1) : 1));
  });

  assert.equal(exitCode, 0);
});

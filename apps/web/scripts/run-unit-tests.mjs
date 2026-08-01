import { readdir } from "node:fs/promises";
import { join } from "node:path";
import { spawn } from "node:child_process";

const TEST_ROOT = join(import.meta.dirname, "../tests/web");
const testFiles = (await readdir(TEST_ROOT))
  .filter((file) => file.endsWith(".test.mjs"))
  .sort()
  .map((file) => join(TEST_ROOT, file));

if (testFiles.length === 0) {
  throw new Error(`No Web unit tests found in ${TEST_ROOT}`);
}

const child = spawn(process.execPath, ["--test", ...testFiles], {
  cwd: join(import.meta.dirname, ".."),
  stdio: "inherit",
});

child.on("error", (error) => {
  console.error(error);
  process.exitCode = 1;
});

child.on("exit", (code, signal) => {
  if (signal !== null) {
    process.exitCode = 1;
    return;
  }
  process.exitCode = code ?? 1;
});

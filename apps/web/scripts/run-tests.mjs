import { spawn } from "node:child_process";
import { dirname } from "node:path";

const WEB_ROOT = dirname(import.meta.dirname);
const PNPM = process.platform === "win32" ? "pnpm.cmd" : "pnpm";

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: WEB_ROOT,
      stdio: "inherit",
      shell: false,
    });

    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (signal !== null) {
        resolve(1);
        return;
      }
      resolve(code ?? 1);
    });
  });
}

const unitExit = await run(process.execPath, ["scripts/run-unit-tests.mjs"]);
if (unitExit !== 0) process.exit(unitExit);

const reactExit = await run(PNPM, ["exec", "vitest", "run"]);
process.exitCode = reactExit;

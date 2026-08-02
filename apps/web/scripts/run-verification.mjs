import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import { spawnInvocation } from "../../../scripts/spawn-command.mjs";

const WEB_ROOT = fileURLToPath(new URL("..", import.meta.url));
const pnpm = process.platform === "win32" ? "pnpm.cmd" : "pnpm";

function runChild(command, args) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (exitCode) => {
      if (settled) return;
      settled = true;
      resolve(exitCode);
    };
    const invocation = spawnInvocation(command, args);
    const child = spawn(invocation.command, invocation.args, {
      cwd: WEB_ROOT,
      shell: false,
      stdio: "inherit",
    });
    child.once("error", () => finish(1));
    child.once("exit", (code, signal) => finish(signal === null ? (code ?? 1) : 1));
  });
}

const commands = [
  [pnpm, ["build"]],
  [process.execPath, ["scripts/verify-production-build.mjs"]],
  [process.execPath, ["scripts/verify-web.mjs"]],
];

for (const [command, args] of commands) {
  const exitCode = await runChild(command, args);
  if (exitCode !== 0) {
    process.exitCode = exitCode;
    break;
  }
}

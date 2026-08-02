import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import test from "node:test";

import {
  stopProcessTree,
  waitForChildSpawn,
} from "../../scripts/process-utils.mjs";

test("stopProcessTree terminates a long-running child", async (t) => {
  const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
    detached: process.platform !== "win32",
    stdio: "ignore",
  });
  t.after(() => {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
  });

  await waitForChildSpawn(child);
  await stopProcessTree(child);

  assert.ok(
    child.exitCode !== null || child.signalCode !== null,
    "child must have exited before cleanup resolves",
  );
});

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import test from "node:test";
import { setTimeout as delay } from "node:timers/promises";

import {
  settleCleanupTasks,
  stopProcessTree,
  waitForChildSpawn,
  waitForServer,
} from "../../scripts/process-utils.mjs";

test("waitForServer respects its deadline when a response hangs", async () => {
  const sockets = new Set();
  const server = createServer(() => {});
  server.on("connection", (socket) => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.notEqual(address, null);
  assert.equal(typeof address, "object");

  try {
    const outcome = await Promise.race([
      waitForServer(`http://127.0.0.1:${address.port}`, 100).then(
        () => "resolved",
        () => "rejected",
      ),
      delay(400, "watchdog"),
    ]);
    assert.equal(outcome, "rejected");
  } finally {
    for (const socket of sockets) socket.destroy();
    await new Promise((resolve) => server.close(resolve));
  }
});

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

test("stopProcessTree falls back to a direct non-detached child", async (t) => {
  const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
    detached: false,
    stdio: "ignore",
  });
  t.after(() => {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
  });
  await waitForChildSpawn(child);

  const outcome = await Promise.race([
    stopProcessTree(child).then(() => "stopped"),
    delay(500, "watchdog"),
  ]);
  assert.equal(outcome, "stopped");
});

test("settleCleanupTasks runs every cleanup after one rejects", async () => {
  const calls = [];
  const failures = await settleCleanupTasks([
    {
      name: "browser",
      run: () => {
        calls.push("browser");
        throw new Error("closed");
      },
    },
    { name: "mock", run: () => calls.push("mock") },
    { name: "web", run: async () => calls.push("web") },
  ]);

  assert.deepEqual(calls, ["browser", "mock", "web"]);
  assert.equal(failures.length, 1);
  assert.equal(failures[0].name, "browser");
  assert.match(String(failures[0].reason), /closed/);
});

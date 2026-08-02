import assert from "node:assert/strict";
import test from "node:test";

import { spawnInvocation } from "../../../../scripts/spawn-command.mjs";

test("Windows batch commands use explicit ComSpec invocation", () => {
  assert.deepEqual(
    spawnInvocation("pnpm.cmd", ["--filter", "cairn-web", "test"], {
      platform: "win32",
      env: { ComSpec: "C:\\Windows\\System32\\cmd.exe" },
    }),
    {
      command: "C:\\Windows\\System32\\cmd.exe",
      args: ["/d", "/s", "/c", "pnpm.cmd", "--filter", "cairn-web", "test"],
    },
  );
});

test("Windows batch commands fall back to cmd.exe", () => {
  assert.deepEqual(
    spawnInvocation("pnpm.cmd", ["build"], { platform: "win32", env: {} }),
    { command: "cmd.exe", args: ["/d", "/s", "/c", "pnpm.cmd", "build"] },
  );
});

test("native executables and non-Windows commands remain direct", () => {
  assert.deepEqual(
    spawnInvocation("uv.exe", ["run"], { platform: "win32", env: {} }),
    { command: "uv.exe", args: ["run"] },
  );
  assert.deepEqual(
    spawnInvocation("pnpm", ["test"], { platform: "linux", env: {} }),
    { command: "pnpm", args: ["test"] },
  );
});

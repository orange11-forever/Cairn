import { spawnSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, copyFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { spawnInvocation } from "./spawn-command.mjs";

const REPOSITORY_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const UV = process.platform === "win32" ? "uv.exe" : "uv";
const PNPM = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const OPENAPI_PATH = join(REPOSITORY_ROOT, "packages/sdk/openapi.json");
const SCHEMA_PATH = join(REPOSITORY_ROOT, "packages/sdk/src/generated/schema.d.ts");

function run(command, args, env = process.env) {
  const invocation = spawnInvocation(command, args, { env });
  const result = spawnSync(invocation.command, invocation.args, {
    cwd: REPOSITORY_ROOT,
    env,
    shell: false,
    stdio: "inherit",
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${command} exited with status ${result.status ?? "unknown"}`);
  }
}

async function sameBytes(left, right) {
  try {
    const [leftBytes, rightBytes] = await Promise.all([readFile(left), readFile(right)]);
    return leftBytes.equals(rightBytes);
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

const checkOnly = process.argv.slice(2).includes("--check");
const temporaryRoot = await mkdtemp(join(tmpdir(), "cairn-sdk-"));
const temporaryOpenapi = join(temporaryRoot, "openapi.json");
const temporarySchema = join(temporaryRoot, "schema.d.ts");

try {
  run(
    UV,
    ["run", "--offline", "--package", "cairn-api", "python", "scripts/export-openapi.py", temporaryOpenapi],
    { ...process.env, UV_CACHE_DIR: join(temporaryRoot, "uv-cache") },
  );
  run(PNPM, [
    "--filter",
    "@cairn/sdk",
    "exec",
    "openapi-typescript",
    temporaryOpenapi,
    "--output",
    temporarySchema,
  ]);

  if (checkOnly) {
    const stale = [];
    if (!(await sameBytes(temporaryOpenapi, OPENAPI_PATH))) stale.push("packages/sdk/openapi.json");
    if (!(await sameBytes(temporarySchema, SCHEMA_PATH))) {
      stale.push("packages/sdk/src/generated/schema.d.ts");
    }
    if (stale.length > 0) {
      console.error(`Stale generated SDK artifacts: ${stale.join(", ")}`);
      process.exitCode = 1;
    }
  } else {
    await mkdir(dirname(SCHEMA_PATH), { recursive: true });
    await copyFile(temporaryOpenapi, OPENAPI_PATH);
    await copyFile(temporarySchema, SCHEMA_PATH);
  }
} finally {
  await rm(temporaryRoot, { recursive: true, force: true });
}

import { execFile as execFileCallback } from "node:child_process";
import { randomBytes } from "node:crypto";
import { dirname, resolve } from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import { resolveDockerCommand } from "./docker-command.mjs";

const execFile = promisify(execFileCallback);
const REPOSITORY_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const COMPOSE_FILE = resolve(REPOSITORY_ROOT, "deploy/compose/core.yml");
const UV = process.platform === "win32" ? "uv.exe" : "uv";

export const MINIO_RELEASE = "RELEASE.2025-10-15T17-29-55Z";

function defaultRunCommand(command, args, options) {
  return execFile(command, args, {
    cwd: REPOSITORY_ROOT,
    maxBuffer: 4 * 1024 * 1024,
    ...options,
  });
}

function parsePublishedPort(output) {
  for (const line of output.trim().split(/\r?\n/)) {
    const match = line.match(/:(\d+)$/);
    if (match !== null) return Number(match[1]);
  }
  throw new Error(`Could not parse MinIO published port from: ${output.trim() || "<empty>"}`);
}

function verifyReleaseVersion(output) {
  const expected = `minio version ${MINIO_RELEASE}`;
  if (!output.includes(expected) || output.includes("DEVELOPMENT.GOGET")) {
    throw new Error(`expected MinIO release ${MINIO_RELEASE}, received: ${output.trim()}`);
  }
}

export function createMinioSmokeProjectName({
  pid = process.pid,
  makeRandomBytes = randomBytes,
} = {}) {
  return `cairn-minio-smoke-${pid}-${makeRandomBytes(4).toString("hex")}`;
}

export async function runMinioSmoke({
  projectName = createMinioSmokeProjectName(),
  environment = process.env,
  dockerCommand = "docker",
  uvCommand = UV,
  runCommand = defaultRunCommand,
} = {}) {
  if (!/^cairn-minio-smoke-[a-z0-9-]+$/.test(projectName)) {
    throw new Error("MinIO smoke project must match ^cairn-minio-smoke-[a-z0-9-]+$");
  }

  const smokeEnvironment = {
    ...environment,
    CAIRN_MINIO_CONSOLE_PORT: "0",
    CAIRN_MINIO_PORT: "0",
    CAIRN_OBJECT_STORE_ACCESS_KEY: "cairn-smoke-access",
    CAIRN_OBJECT_STORE_SECRET_KEY: "cairn-smoke-secret-change-me",
  };
  const composePrefix = ["compose", "-f", COMPOSE_FILE, "-p", projectName];
  let failure;

  try {
    await runCommand(
      dockerCommand,
      [...composePrefix, "up", "-d", "--build", "--wait", "minio"],
      { env: smokeEnvironment },
    );
    const version = await runCommand(
      dockerCommand,
      [...composePrefix, "exec", "-T", "minio", "minio", "--version"],
      { env: smokeEnvironment },
    );
    verifyReleaseVersion(version.stdout);

    const publishedPort = await runCommand(
      dockerCommand,
      [...composePrefix, "port", "minio", "9000"],
      { env: smokeEnvironment },
    );
    const endpoint = `http://127.0.0.1:${parsePublishedPort(publishedPort.stdout)}`;
    await runCommand(
      uvCommand,
      [
        "run",
        "--package",
        "cairn-api",
        "python",
        "scripts/minio-object-smoke.py",
        endpoint,
      ],
      { env: smokeEnvironment },
    );
  } catch (error) {
    failure = error;
  }

  try {
    await runCommand(
      dockerCommand,
      [...composePrefix, "down", "--volumes", "--remove-orphans"],
      { env: smokeEnvironment },
    );
  } catch (cleanupError) {
    if (failure === undefined) throw cleanupError;
    failure = new Error(
      `${failure instanceof Error ? failure.message : String(failure)}; ` +
        `cleanup failed: ${cleanupError instanceof Error ? cleanupError.message : String(cleanupError)}`,
      { cause: failure },
    );
  }

  if (failure !== undefined) throw failure;
}

const entryPath = process.argv[1];
const isMain = entryPath !== undefined && resolve(entryPath) === fileURLToPath(import.meta.url);

if (isMain) {
  try {
    const dockerCommand = await resolveDockerCommand();
    await runMinioSmoke({ dockerCommand });
    console.log(`MinIO smoke passed for ${MINIO_RELEASE}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.startsWith("Unable to reach a Docker engine.")) {
      console.log(`SKIP: MinIO smoke unavailable: ${message}`);
    } else {
      console.error(message);
      process.exitCode = 1;
    }
  }
}

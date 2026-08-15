import { execFile as execFileCallback } from "node:child_process";
import { randomBytes } from "node:crypto";
import { dirname, resolve } from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import {
  DockerClientNotFoundError,
  dockerEnvironment,
  resolveDockerCommand,
} from "./docker-command.mjs";

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
  const release = output.match(/(?:^|\n)minio version ([^\s]+)/)?.[1];
  if (release !== MINIO_RELEASE || output.includes("DEVELOPMENT.GOGET")) {
    throw new Error(`expected MinIO release ${MINIO_RELEASE}, received: ${output.trim()}`);
  }
}

export async function runMinioSmokeCli({
  resolveDocker = resolveDockerCommand,
  smoke = runMinioSmoke,
  log = console.log,
  reportError = console.error,
} = {}) {
  try {
    const dockerCommand = await resolveDocker();
    await smoke({ dockerCommand });
    log(`MinIO smoke passed for ${MINIO_RELEASE}`);
    return 0;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (error instanceof DockerClientNotFoundError) {
      log(`SKIP: MinIO smoke unavailable: ${message}`);
      return 0;
    }
    reportError(message);
    return 1;
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
  platform = process.platform,
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
  const composeEnvironment = dockerEnvironment({
    dockerCommand,
    env: smokeEnvironment,
    platform,
  });
  const composePrefix = ["compose", "-f", COMPOSE_FILE, "-p", projectName];
  let failure;

  try {
    await runCommand(
      dockerCommand,
      [...composePrefix, "up", "-d", "--build", "--wait", "minio"],
      { env: composeEnvironment },
    );
    const version = await runCommand(
      dockerCommand,
      [...composePrefix, "exec", "-T", "minio", "minio", "--version"],
      { env: composeEnvironment },
    );
    verifyReleaseVersion(version.stdout);

    const publishedPort = await runCommand(
      dockerCommand,
      [...composePrefix, "port", "minio", "9000"],
      { env: composeEnvironment },
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
      { env: composeEnvironment },
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
  process.exitCode = await runMinioSmokeCli();
}

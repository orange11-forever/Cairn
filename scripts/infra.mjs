import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { resolveDockerCommand, runCompose } from "./docker-command.mjs";
import { spawnInvocation } from "./spawn-command.mjs";

const ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const COMPOSE_FILE = resolve(ROOT, "deploy/compose/core.yml");
const PROJECT_PATTERN = /^cairn-test-[a-z0-9-]+$/;
const UV = process.platform === "win32" ? "uv.exe" : "uv";

function valueFor(args, name, fallback) {
  const index = args.indexOf(name);
  return index === -1 ? fallback : args[index + 1];
}

function validateProject(project) {
  if (!project || !PROJECT_PATTERN.test(project)) {
    console.error("Project must match ^cairn-test-[a-z0-9-]+$");
    return false;
  }
  return true;
}

function runObjectStoreBootstrap(environment) {
  return new Promise((resolveExitCode) => {
    const invocation = spawnInvocation(UV, [
      "run",
      "--package",
      "cairn-api",
      "cairn-api",
      "object-store-bootstrap",
    ]);
    const child = spawn(invocation.command, invocation.args, {
      cwd: ROOT,
      env: environment,
      shell: false,
      stdio: "inherit",
    });
    child.once("error", () => resolveExitCode(1));
    child.once("exit", (code, signal) => {
      resolveExitCode(signal === null ? (code ?? 1) : 1);
    });
  });
}

export async function runInfra(
  action,
  args = process.argv.slice(3),
  env = process.env,
  operations = {},
) {
  if (!["up", "config", "test-up", "test-down"].includes(action)) return 2;
  const project = valueFor(args, "--project");
  if ((action === "test-up" || action === "test-down") && !validateProject(project)) return 2;
  const resolveDocker = operations.resolveDocker ?? resolveDockerCommand;
  const compose = operations.compose ?? runCompose;
  const bootstrap = operations.bootstrap ?? runObjectStoreBootstrap;
  const dockerCommand = await resolveDocker({ env });
  if (action === "up") {
    const startupCode = await compose({
      dockerCommand,
      args: [
        "-f",
        COMPOSE_FILE,
        "up",
        "-d",
        "--build",
        "--wait",
        "postgres",
        "minio",
      ],
      env,
      stdio: "inherit",
    });
    if (startupCode !== 0) return startupCode;
    const bootstrapEnvironment = { ...env };
    const minioPort = env.CAIRN_MINIO_PORT ?? "9000";
    bootstrapEnvironment.CAIRN_OBJECT_STORE_ENDPOINT_URL ??= `http://127.0.0.1:${minioPort}`;
    bootstrapEnvironment.CAIRN_OBJECT_STORE_PUBLIC_ENDPOINT_URL ??=
      bootstrapEnvironment.CAIRN_OBJECT_STORE_ENDPOINT_URL;
    return bootstrap(bootstrapEnvironment);
  }
  if (action === "config") {
    return compose({
      dockerCommand,
      args: ["-f", COMPOSE_FILE, "config"],
      env,
      stdio: "inherit",
    });
  }
  const composeArgs = ["-f", COMPOSE_FILE];
  if (project) composeArgs.push("--project-name", project);
  if (action === "test-up") composeArgs.push("up", "-d", "--wait", "postgres");
  else if (action === "test-down") composeArgs.push("down", "--volumes", "--remove-orphans");
  const childEnv = { ...env };
  const port = valueFor(args, "--port");
  const database = valueFor(args, "--database");
  if (port) childEnv.CAIRN_POSTGRES_PORT = port;
  if (database) childEnv.POSTGRES_DB = database;
  return compose({ dockerCommand, args: composeArgs, env: childEnv, stdio: "inherit" });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const action = process.argv[2];
  try {
    process.exitCode = await runInfra(action);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

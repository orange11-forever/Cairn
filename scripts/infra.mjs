import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { resolveDockerCommand, runCompose } from "./docker-command.mjs";

const ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const COMPOSE_FILE = resolve(ROOT, "deploy/compose/core.yml");
const PROJECT_PATTERN = /^cairn-test-[a-z0-9-]+$/;

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

export async function runInfra(action, args = process.argv.slice(3), env = process.env) {
  if (!["up", "config", "test-up", "test-down"].includes(action)) return 2;
  const project = valueFor(args, "--project");
  if ((action === "test-up" || action === "test-down") && !validateProject(project)) return 2;
  const dockerCommand = await resolveDockerCommand({ env });
  if (action === "up") {
    return runCompose({
      dockerCommand,
      args: ["-f", COMPOSE_FILE, "up", "-d", "--wait", "postgres"],
      env,
      stdio: "inherit",
    });
  }
  if (action === "config") {
    return runCompose({
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
  return runCompose({ dockerCommand, args: composeArgs, env: childEnv, stdio: "inherit" });
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

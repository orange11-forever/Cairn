import { spawn } from "node:child_process";
import { basename } from "node:path";

const COMPOSE_INTERPOLATION_VARIABLES = [
  "CAIRN_POSTGRES_PORT",
  "POSTGRES_DB",
  "POSTGRES_USER",
  "POSTGRES_PASSWORD",
];

function probeDocker(command, env) {
  return new Promise((resolve) => {
    const child = spawn(command, ["version", "--format", "{{.Server.Version}}"], {
      env,
      shell: false,
      stdio: "ignore",
    });
    child.once("error", () => resolve(false));
    child.once("exit", (code) => resolve(code === 0));
  });
}

export async function resolveDockerCommand({
  env = process.env,
  platform = process.platform,
  probe = (candidate) => probeDocker(candidate, env),
} = {}) {
  const native = platform === "win32" ? "docker.exe" : "docker";
  const candidates = [env.CAIRN_DOCKER_COMMAND, native, "docker.exe"].filter(Boolean);
  const unique = [...new Set(candidates)];
  const attempts = [];
  for (const candidate of unique) {
    attempts.push(candidate);
    if (await probe(candidate)) return candidate;
  }
  throw new Error(
    `Unable to reach a Docker engine. Tried: ${attempts.join(", ")}. ` +
      "Set CAIRN_DOCKER_COMMAND to a working Docker client.",
  );
}

export function dockerEnvironment({
  dockerCommand,
  env = process.env,
  platform = process.platform,
}) {
  if (platform !== "linux" || basename(dockerCommand).toLowerCase() !== "docker.exe") {
    return env;
  }
  const entries = (env.WSLENV ?? "").split(":").filter(Boolean);
  const forwardedNames = new Set(entries.map((entry) => entry.split("/", 1)[0]));
  const additions = COMPOSE_INTERPOLATION_VARIABLES.filter(
    (name) => env[name] !== undefined && !forwardedNames.has(name),
  );
  if (additions.length === 0) return env;
  return { ...env, WSLENV: [...entries, ...additions].join(":") };
}

export function runCompose({
  dockerCommand,
  args,
  env = process.env,
  platform = process.platform,
  stdio = "inherit",
}) {
  return new Promise((resolveExitCode) => {
    const child = spawn(dockerCommand, ["compose", ...args], {
      env: dockerEnvironment({ dockerCommand, env, platform }),
      shell: false,
      stdio,
    });
    child.once("error", (error) => {
      if (stdio === "inherit") console.error(`Failed to start Docker: ${error.message}`);
      resolveExitCode(1);
    });
    child.once("exit", (code, signal) => {
      resolveExitCode(signal === null ? (code ?? 1) : 1);
    });
  });
}

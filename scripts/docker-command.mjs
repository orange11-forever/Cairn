import { spawn } from "node:child_process";

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

export function runCompose({ dockerCommand, args, env = process.env, stdio = "inherit" }) {
  return new Promise((resolveExitCode) => {
    const child = spawn(dockerCommand, ["compose", ...args], {
      env,
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

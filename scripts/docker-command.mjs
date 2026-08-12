import { spawn } from "node:child_process";
import { basename } from "node:path";

const COMPOSE_INTERPOLATION_VARIABLES = [
  "CAIRN_POSTGRES_PORT",
  "POSTGRES_DB",
  "POSTGRES_USER",
  "POSTGRES_PASSWORD",
  "CORS_ORIGINS",
  "CAIRN_MINIO_PORT",
  "CAIRN_MINIO_CONSOLE_PORT",
  "CAIRN_OBJECT_STORE_ACCESS_KEY",
  "CAIRN_OBJECT_STORE_SECRET_KEY",
  "CAIRN_BUILD_HTTP_PROXY",
  "CAIRN_BUILD_HTTPS_PROXY",
  "NO_PROXY",
  "CAIRN_BUILD_CA_CERT_BASE64",
];

function containerProxyUrl(value) {
  try {
    const proxy = new URL(value);
    if (["127.0.0.1", "localhost", "[::1]"].includes(proxy.hostname)) {
      proxy.hostname = "host.docker.internal";
    }
    return proxy.href;
  } catch {
    return value;
  }
}

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
  const bridged = { ...env };
  const httpProxy = env.CAIRN_BUILD_HTTP_PROXY ?? env.HTTP_PROXY ?? env.http_proxy;
  const httpsProxy = env.CAIRN_BUILD_HTTPS_PROXY ?? env.HTTPS_PROXY ?? env.https_proxy;
  const noProxy = env.NO_PROXY ?? env.no_proxy;
  if (httpProxy !== undefined) bridged.CAIRN_BUILD_HTTP_PROXY = containerProxyUrl(httpProxy);
  if (httpsProxy !== undefined) bridged.CAIRN_BUILD_HTTPS_PROXY = containerProxyUrl(httpsProxy);
  if (noProxy !== undefined) bridged.NO_PROXY = noProxy;

  const entries = (bridged.WSLENV ?? "").split(":").filter(Boolean);
  const forwardedNames = new Set(entries.map((entry) => entry.split("/", 1)[0]));
  const additions = COMPOSE_INTERPOLATION_VARIABLES.filter(
    (name) => bridged[name] !== undefined && !forwardedNames.has(name),
  );
  if (additions.length === 0) return bridged;
  return { ...bridged, WSLENV: [...entries, ...additions].join(":") };
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

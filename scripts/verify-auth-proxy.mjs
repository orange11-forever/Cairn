import { execFile as execFileCallback, spawn } from "node:child_process";
import { createHash, X509Certificate } from "node:crypto";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer as createHttpsServer } from "node:https";
import { request as httpRequest } from "node:http";
import { createServer as createNetServer } from "node:net";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import { stopProcessTree, waitForServer } from "../apps/web/scripts/process-utils.mjs";
import { spawnInvocation } from "./spawn-command.mjs";

const execFile = promisify(execFileCallback);
const REPOSITORY_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const UV = process.platform === "win32" ? "uv.exe" : "uv";
const requireWebDependency = createRequire(resolve(REPOSITORY_ROOT, "apps/web/package.json"));

function readPort(environment, name, fallback) {
  const raw = environment[name] ?? String(fallback);
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${name} must be an integer between 1 and 65535, received ${raw}`);
  }
  return port;
}

export function resolveAuthProxyConfig(
  environment = process.env,
  { projectName = "cairn-verify-auth-proxy" } = {},
) {
  const databasePort = readPort(environment, "CAIRN_VERIFY_POSTGRES_PORT", 55436);
  const apiPort = readPort(environment, "CAIRN_VERIFY_API_PORT", 58080);
  const webPort = readPort(environment, "CAIRN_VERIFY_WEB_PORT", 55500);
  const proxyPort = readPort(environment, "CAIRN_VERIFY_PROXY_PORT", 58443);
  const proxyOrigin = `https://localhost:${proxyPort}`;
  const databaseUrl = environment.CAIRN_TEST_DATABASE_URL
    ?? `postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:${databasePort}/cairn_test`;

  return {
    projectName,
    databasePort,
    apiPort,
    webPort,
    proxyPort,
    proxyOrigin,
    internalApiOrigin: `http://127.0.0.1:${apiPort}`,
    productionApiOrigin: `https://localhost:${apiPort}`,
    productionWebOrigin: `https://localhost:${webPort}`,
    databaseUrl,
    environment: {
      ...environment,
      APP_URL: proxyOrigin,
      CAIRN_AUTH_RATE_LIMIT_SECRET: "proxy-verification-rate-limit-secret-at-least-32-bytes",
      CAIRN_CSRF_SECRET: "proxy-verification-csrf-secret-at-least-32-bytes",
      CAIRN_ENVIRONMENT: "production",
      CAIRN_HTTP_PORT: String(apiPort),
      CAIRN_OBJECT_STORE_ACCESS_KEY: "proxy-verification-object-store-access",
      CAIRN_OBJECT_STORE_SECRET_KEY: "proxy-verification-object-store-secret",
      CAIRN_SEARCH_AUDIT_SECRET: "proxy-verification-search-audit-secret-at-least-32-bytes",
      CAIRN_SESSION_COOKIE_SECURE: "true",
      CAIRN_TRUSTED_PROXY_CIDRS: "127.0.0.0/8,::1/128",
      CAIRN_VERIFY_PROXY_PORT: String(proxyPort),
      CORS_ORIGINS: proxyOrigin,
      DATABASE_URL: databaseUrl,
      EMBEDDING_API_KEY: "proxy-verification-embedding-key",
      VITE_IDENTITY_API_URL: proxyOrigin,
    },
  };
}

function canonicalPeer(value) {
  if (value === undefined || value === null || value === "") return "unknown";
  return value.startsWith("::ffff:") ? value.slice("::ffff:".length) : value;
}

export function buildProxyHeaders(headers, remoteAddress, forwardedHost) {
  const forwarded = { ...headers };
  for (const name of Object.keys(forwarded)) {
    if (name.toLowerCase().startsWith("x-forwarded-") || name.toLowerCase() === "forwarded") {
      delete forwarded[name];
    }
  }
  forwarded["x-forwarded-for"] = canonicalPeer(remoteAddress);
  forwarded["x-forwarded-host"] = forwardedHost;
  forwarded["x-forwarded-proto"] = "https";
  return forwarded;
}

export function chromiumLaunchOptionsForCertificate(certificate) {
  const parsed = new X509Certificate(certificate);
  const publicKey = parsed.publicKey.export({ type: "spki", format: "der" });
  const spkiHash = createHash("sha256").update(publicKey).digest("base64");
  return {
    headless: true,
    args: [`--ignore-certificate-errors-spki-list=${spkiHash}`],
  };
}

async function generateCertificate({ directory, certPath, keyPath, opensslCommand }) {
  try {
    await execFile(
      opensslCommand,
      [
        "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", keyPath,
        "-out", certPath,
        "-days", "1",
        "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1",
      ],
      { cwd: directory },
    );
  } catch (error) {
    if (error?.code === "ENOENT") {
      throw new Error(
        `OpenSSL is required for HTTPS proxy verification. Install openssl or set an available opensslCommand (attempted: ${opensslCommand}).`,
        { cause: error },
      );
    }
    throw new Error(`OpenSSL could not generate the temporary localhost certificate: ${error.message}`, {
      cause: error,
    });
  }
}

function closeServer(server) {
  if (server === null || !server.listening) return Promise.resolve();
  return new Promise((resolveClose, rejectClose) => {
    server.close((error) => error ? rejectClose(error) : resolveClose());
    server.closeAllConnections?.();
  });
}

async function startHttpsProxy({ certPath, keyPath, config }) {
  const [cert, key] = await Promise.all([readFile(certPath), readFile(keyPath)]);
  const target = new URL(config.internalApiOrigin);
  const server = createHttpsServer({ cert, key }, (request, response) => {
    if (request.method === "GET" && request.url === "/") {
      response.writeHead(200, {
        "content-type": "text/html; charset=utf-8",
        "content-security-policy": "default-src 'none'; script-src 'unsafe-inline'; connect-src 'self'",
      });
      response.end("<!doctype html><title>Cairn auth proxy verification</title>");
      return;
    }

    const forwarded = httpRequest({
      protocol: target.protocol,
      hostname: target.hostname,
      port: target.port,
      method: request.method,
      path: request.url,
      headers: buildProxyHeaders(
        request.headers,
        request.socket.remoteAddress,
        request.headers.host ?? `localhost:${config.proxyPort}`,
      ),
    }, (upstream) => {
      response.writeHead(upstream.statusCode ?? 502, upstream.headers);
      upstream.pipe(response);
    });
    forwarded.once("error", (error) => {
      if (!response.headersSent) response.writeHead(502, { "content-type": "text/plain" });
      response.end(`proxy upstream unavailable: ${error.message}`);
    });
    request.once("aborted", () => forwarded.destroy());
    request.pipe(forwarded);
  });
  server.on("clientError", (_error, socket) => socket.destroy());
  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(config.proxyPort, "127.0.0.1", () => {
      server.removeListener("error", rejectListen);
      resolveListen();
    });
  });
  return { stop: () => closeServer(server) };
}

function availablePort() {
  return new Promise((resolvePort, rejectPort) => {
    const server = createNetServer();
    server.once("error", rejectPort);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (typeof address !== "object" || address === null) {
        server.close();
        rejectPort(new Error("Could not allocate a loopback API port"));
        return;
      }
      const port = address.port;
      server.close((error) => error ? rejectPort(error) : resolvePort(port));
    });
  });
}

async function startApiProcess({
  config,
  signal,
  spawnProcess = spawn,
  waitForUrl = waitForServer,
}) {
  const invocation = spawnInvocation(UV, ["run", "--package", "cairn-api", "cairn-api"]);
  const child = spawnProcess(invocation.command, invocation.args, {
    cwd: REPOSITORY_ROOT,
    detached: process.platform !== "win32",
    env: config.environment,
    shell: false,
    stdio: "inherit",
  });
  const failed = new Promise((_, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      reject(new Error(`Production verification API exited before readiness (code=${code}, signal=${signal})`));
    });
  });
  const stopOnAbort = () => { void stopProcessTree(child); };
  signal?.addEventListener("abort", stopOnAbort, { once: true });
  try {
    await Promise.race([waitForUrl(`${config.internalApiOrigin}/ready`), failed]);
  } catch (error) {
    await stopProcessTree(child);
    throw error;
  } finally {
    signal?.removeEventListener("abort", stopOnAbort);
  }
  return { stop: () => stopProcessTree(child) };
}

function requestViaProxy(origin, path, { method = "GET", headers = {}, body } = {}) {
  return import("node:https").then(({ request }) => new Promise((resolveRequest, rejectRequest) => {
    const outgoing = request(new URL(path, origin), {
      method,
      headers,
      rejectUnauthorized: false,
    }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => resolveRequest({
        status: response.statusCode ?? 0,
        headers: response.headers,
        body: Buffer.concat(chunks).toString("utf8"),
      }));
    });
    outgoing.once("error", rejectRequest);
    if (body !== undefined) outgoing.write(body);
    outgoing.end();
  }));
}

function verify(condition, message) {
  if (!condition) throw new Error(message);
}

async function queryAuditIp(config, traceId) {
  const code = [
    "from sqlalchemy import select",
    "from cairn_api.audit.models import AuditLog",
    "from cairn_api.db.session import Database",
    "from cairn_api.settings import Settings",
    "db=Database(Settings().database_url)",
    `trace_id=${JSON.stringify(traceId)}`,
    "session=db.session_factory()",
    "print(session.scalar(select(AuditLog.ip).where(AuditLog.trace_id == trace_id)) or '')",
    "session.close()",
    "db.dispose()",
  ].join("; ");
  const { stdout } = await execFile(
    UV,
    ["run", "--package", "cairn-api", "python", "-c", code],
    { cwd: REPOSITORY_ROOT, env: config.environment },
  );
  return stdout.trim();
}

async function runChromiumAssertions({ certPath, config, setBrowser }) {
  const preflight = await requestViaProxy(config.proxyOrigin, "/api/v1/login", {
    method: "OPTIONS",
    headers: {
      Origin: config.proxyOrigin,
      "Access-Control-Request-Method": "POST",
      "Access-Control-Request-Headers": "content-type,x-request-id",
    },
  });
  verify(preflight.status === 200, `CORS preflight returned ${preflight.status}`);
  verify(preflight.headers["access-control-allow-origin"] === config.proxyOrigin, "CORS preflight did not allow the production web origin");
  verify(preflight.headers["access-control-allow-credentials"] === "true", "CORS preflight did not allow credentials");

  const denied = await requestViaProxy(config.proxyOrigin, "/api/v1/login", {
    method: "POST",
    headers: { Origin: "https://attacker.example", "content-type": "application/json" },
    body: JSON.stringify({ email: "demo@cairn.dev", password: "cairn-demo-2026" }),
  });
  verify(denied.status === 403, `untrusted Origin returned ${denied.status} instead of 403`);

  const { chromium } = requireWebDependency("playwright");
  const certificate = await readFile(certPath);
  const browser = await chromium.launch(chromiumLaunchOptionsForCertificate(certificate));
  setBrowser(browser);
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`${config.proxyOrigin}/`, { waitUntil: "domcontentloaded" });
  const traceId = "auth-proxy-browser-login";
  const login = await page.evaluate(async ({ traceId }) => {
    const login = await fetch("/api/v1/login", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Origin: location.origin,
        "X-Request-ID": traceId,
      },
      body: JSON.stringify({ email: "demo@cairn.dev", password: "cairn-demo-2026" }),
    });
    const identity = await login.json();
    return {
      loginStatus: login.status,
      identity,
      documentCookie: document.cookie,
    };
  }, { traceId });
  verify(login.loginStatus === 200, `login returned ${login.loginStatus}`);
  verify(!login.documentCookie.includes("cairn_session"), "HttpOnly session cookie was visible to script");
  const cookies = await context.cookies(config.proxyOrigin);
  const sessionCookie = cookies.find((cookie) => cookie.name === "cairn_session");
  verify(sessionCookie !== undefined, "Chromium did not store the session cookie");
  verify(sessionCookie.secure, "session cookie is missing Secure");
  verify(sessionCookie.httpOnly, "session cookie is missing HttpOnly");
  verify(sessionCookie.sameSite === "Lax", `session cookie SameSite was ${sessionCookie.sameSite}`);
  verify(sessionCookie.path === "/", `session cookie Path was ${sessionCookie.path}`);

  const lifecycle = await page.evaluate(async () => {
    const restored = await fetch("/api/v1/session", { credentials: "include" });
    const badLogout = await fetch("/api/v1/logout", {
      method: "POST",
      credentials: "include",
      headers: { Origin: location.origin, "X-CSRF-Token": "wrong" },
    });
    return {
      restoredStatus: restored.status,
      badLogoutStatus: badLogout.status,
    };
  });
  verify(lifecycle.restoredStatus === 200, `session restore returned ${lifecycle.restoredStatus}`);
  verify(lifecycle.badLogoutStatus === 403, `logout without valid CSRF returned ${lifecycle.badLogoutStatus}`);

  await context.clearCookies();
  const cleared = await page.evaluate(() => fetch("/api/v1/session", { credentials: "include" }).then((response) => response.status));
  verify(cleared === 401, `cleared browser cookies returned ${cleared} instead of 401`);
  await context.addCookies([sessionCookie]);
  const logoutStatus = await page.evaluate(({ csrfToken }) => fetch("/api/v1/logout", {
    method: "POST",
    credentials: "include",
    headers: { Origin: location.origin, "X-CSRF-Token": csrfToken },
  }).then((response) => response.status), { csrfToken: login.identity.csrfToken });
  verify(logoutStatus === 204, `CSRF-protected logout returned ${logoutStatus}`);
  verify((await context.cookies(config.proxyOrigin)).every((cookie) => cookie.name !== "cairn_session"), "logout did not remove the browser session cookie");
  const auditIp = await queryAuditIp(config, traceId);
  verify(auditIp === "127.0.0.1", `audit IP was ${auditIp || "missing"}, expected proxy-overwritten 127.0.0.1`);
  return 0;
}

export function createAuthProxyVerification(options = {}) {
  const baseConfig = options.config ?? resolveAuthProxyConfig(options.environment, {
    projectName: options.projectName,
  });
  const certificateGenerator = options.certificateGenerator ?? generateCertificate;
  const startProxy = options.startProxy ?? startHttpsProxy;
  const startApi = options.startApi ?? ((input) => startApiProcess({
    ...input,
    spawnProcess: options.spawnProcess,
    waitForUrl: options.waitForUrl,
  }));
  const runBrowser = options.runBrowser ?? runChromiumAssertions;
  const abortController = new AbortController();
  let directory = null;
  let proxy = null;
  let api = null;
  let browser = null;
  let stopPromise = null;
  let started = false;

  async function stop() {
    if (stopPromise !== null) return stopPromise;
    abortController.abort();
    const cleanupPromise = (async () => {
      const resources = [
        browser === null ? null : () => browser.close(),
        proxy === null ? null : () => proxy.stop(),
        api === null ? null : () => api.stop(),
      ].filter(Boolean);
      const results = await Promise.allSettled(resources.map((cleanup) => cleanup()));
      browser = null;
      proxy = null;
      api = null;
      if (directory !== null) {
        await rm(directory, { recursive: true, force: true });
        directory = null;
      }
      const failure = results.find((result) => result.status === "rejected");
      if (failure?.status === "rejected") throw failure.reason;
    })();
    stopPromise = cleanupPromise;
    try {
      await cleanupPromise;
    } finally {
      if (stopPromise === cleanupPromise) stopPromise = null;
    }
  }

  function throwIfStopped() {
    if (abortController.signal.aborted) {
      throw new Error("auth proxy verification was stopped");
    }
  }

  async function run() {
    if (started) throw new Error("auth proxy verification can only run once");
    started = true;
    directory = await mkdtemp(join(options.temporaryRoot ?? tmpdir(), "cairn-auth-proxy-"));
    const certPath = join(directory, "localhost.crt");
    const keyPath = join(directory, "localhost.key");
    try {
      await certificateGenerator({
        directory,
        certPath,
        keyPath,
        opensslCommand: options.opensslCommand ?? "openssl",
      });
      throwIfStopped();
      const apiPort = options.apiPort ?? await availablePort();
      throwIfStopped();
      const config = {
        ...baseConfig,
        apiPort,
        internalApiOrigin: `http://127.0.0.1:${apiPort}`,
        environment: {
          ...baseConfig.environment,
          CAIRN_HTTP_PORT: String(apiPort),
        },
      };
      proxy = await startProxy({ certPath, keyPath, config, signal: abortController.signal });
      throwIfStopped();
      api = await startApi({ config, signal: abortController.signal });
      throwIfStopped();
      return await runBrowser({
        certPath,
        config,
        signal: abortController.signal,
        setBrowser(value) { browser = value; },
      });
    } finally {
      await stop();
    }
  }

  return Promise.resolve({ run, stop });
}

function installSignalCleanup(verification) {
  let handling = false;
  const handle = (signal) => {
    if (handling) return;
    handling = true;
    void verification.stop().finally(() => {
      process.exitCode = 1;
      process.removeListener("SIGINT", onInterrupt);
      process.removeListener("SIGTERM", onTerminate);
    });
  };
  const onInterrupt = () => handle("SIGINT");
  const onTerminate = () => handle("SIGTERM");
  process.on("SIGINT", onInterrupt);
  process.on("SIGTERM", onTerminate);
  return () => {
    process.removeListener("SIGINT", onInterrupt);
    process.removeListener("SIGTERM", onTerminate);
  };
}

const entryPath = process.argv[1];
const isMain = entryPath !== undefined && resolve(entryPath) === fileURLToPath(import.meta.url);
if (isMain) {
  const verification = await createAuthProxyVerification();
  const disposeSignals = installSignalCleanup(verification);
  try {
    process.exitCode = await verification.run();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  } finally {
    await verification.stop();
    disposeSignals();
  }
}

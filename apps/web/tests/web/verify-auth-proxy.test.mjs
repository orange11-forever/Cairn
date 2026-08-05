import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { rootCertificates } from "node:tls";
import test from "node:test";

import {
  buildProxyHeaders,
  chromiumLaunchOptionsForCertificate,
  createAuthProxyVerification,
  resolveAuthProxyConfig,
} from "../../../../scripts/verify-auth-proxy.mjs";
import { resolveVerificationConfig } from "../../../../scripts/verify-core.mjs";

const fakeProxy = async () => ({ stop: async () => undefined });

test("production verification config uses HTTPS origins and a trusted loopback proxy", () => {
  const config = resolveAuthProxyConfig({
    CAIRN_VERIFY_POSTGRES_PORT: "55499",
    CAIRN_VERIFY_API_PORT: "58099",
    CAIRN_VERIFY_WEB_PORT: "55099",
    CAIRN_VERIFY_PROXY_PORT: "58499",
  }, { projectName: "cairn-verify-fixed-deadbeef" });

  assert.equal(config.proxyOrigin, "https://localhost:58499");
  assert.equal(config.productionApiOrigin, "https://localhost:58099");
  assert.equal(config.productionWebOrigin, "https://localhost:55099");
  assert.equal(config.environment.CAIRN_TRUSTED_PROXY_CIDRS, "127.0.0.0/8,::1/128");
  assert.equal(config.environment.CAIRN_SESSION_COOKIE_SECURE, "true");
  assert.equal(config.environment.CAIRN_ENVIRONMENT, "production");
});

test("core config adds production origins without changing normal local service origins", () => {
  const config = resolveVerificationConfig({
    CAIRN_VERIFY_API_PORT: "58099",
    CAIRN_VERIFY_WEB_PORT: "55099",
    CAIRN_VERIFY_PROXY_PORT: "58499",
  }, { projectName: "cairn-verify-fixed-deadbeef" });

  assert.equal(config.apiOrigin, "http://localhost:58099");
  assert.equal(config.webOrigin, "http://localhost:55099");
  assert.equal(config.productionProxyOrigin, "https://localhost:58499");
  assert.equal(config.productionApiOrigin, "https://localhost:58099");
  assert.equal(config.productionWebOrigin, "https://localhost:55099");
  assert.equal(config.productionEnvironment.CAIRN_TRUSTED_PROXY_CIDRS, "127.0.0.0/8,::1/128");
});

test("missing OpenSSL reports an actionable dependency error", async () => {
  const verification = await createAuthProxyVerification({
    apiPort: 58081,
    opensslCommand: "cairn-openssl-does-not-exist",
    spawnProcess: () => {
      throw new Error("spawn should not be reached");
    },
  });

  await assert.rejects(
    verification.run(),
    /OpenSSL is required.*openssl/i,
  );
  await verification.stop();
});

test("the proxy replaces browser-supplied forwarding headers with the TCP peer", () => {
  const headers = buildProxyHeaders({
    host: "localhost:58443",
    "x-forwarded-for": "203.0.113.99",
    "x-forwarded-host": "attacker.example",
    "x-forwarded-proto": "http",
  }, "127.0.0.1", "localhost:58443");

  assert.equal(headers["x-forwarded-for"], "127.0.0.1");
  assert.equal(headers["x-forwarded-host"], "localhost:58443");
  assert.equal(headers["x-forwarded-proto"], "https");
});

test("Chromium trusts only the generated certificate SPKI", () => {
  assert.ok(rootCertificates.length >= 2);

  const first = chromiumLaunchOptionsForCertificate(rootCertificates[0]);
  const second = chromiumLaunchOptionsForCertificate(rootCertificates[1]);

  assert.equal(first.headless, true);
  assert.equal(first.args.length, 1);
  assert.match(first.args[0], /^--ignore-certificate-errors-spki-list=[A-Za-z0-9+/]+={0,2}$/);
  assert.notEqual(first.args[0], second.args[0]);
  assert.ok(!first.args.includes("--ignore-certificate-errors"));
});

test("temporary certificates are removed after a successful run", async () => {
  let tempDirectory;
  const verification = await createAuthProxyVerification({
    apiPort: 58082,
    certificateGenerator: async ({ directory }) => {
      tempDirectory = directory;
    },
    startProxy: fakeProxy,
    startApi: async () => ({ stop: async () => undefined }),
    runBrowser: async () => 0,
  });

  assert.equal(await verification.run(), 0);
  assert.equal(existsSync(tempDirectory), false);
});

test("temporary certificates and API are removed when browser verification fails", async () => {
  let tempDirectory;
  let stopped = false;
  const verification = await createAuthProxyVerification({
    apiPort: 58083,
    certificateGenerator: async ({ directory }) => {
      tempDirectory = directory;
    },
    startProxy: fakeProxy,
    startApi: async () => ({ stop: async () => { stopped = true; } }),
    runBrowser: async () => { throw new Error("browser failed"); },
  });

  await assert.rejects(verification.run(), /browser failed/);
  assert.equal(stopped, true);
  assert.equal(existsSync(tempDirectory), false);
});

test("stop is idempotent and awaits child API shutdown", async () => {
  let stopCalls = 0;
  let resolveStarted;
  const started = new Promise((resolve) => { resolveStarted = resolve; });
  const verification = await createAuthProxyVerification({
    apiPort: 58084,
    certificateGenerator: async () => undefined,
    startProxy: fakeProxy,
    startApi: async () => ({
      stop: async () => {
        stopCalls += 1;
      },
    }),
    runBrowser: async () => {
      resolveStarted();
      return new Promise(() => undefined);
    },
  });

  const running = verification.run();
  await started;
  await verification.stop();
  await verification.stop();
  assert.equal(stopCalls, 1);
  assert.equal(await Promise.race([running, Promise.resolve(1)]), 1);
});

test("stop during proxy startup closes the late server and prevents API startup", async () => {
  let resolveProxyStarted;
  const proxyStarted = new Promise((resolve) => { resolveProxyStarted = resolve; });
  let resolveProxy;
  const pendingProxy = new Promise((resolve) => { resolveProxy = resolve; });
  let proxyStopCalls = 0;
  let apiStarts = 0;
  const verification = await createAuthProxyVerification({
    apiPort: 58085,
    certificateGenerator: async () => undefined,
    startProxy: async () => {
      resolveProxyStarted();
      return pendingProxy;
    },
    startApi: async () => {
      apiStarts += 1;
      return { stop: async () => undefined };
    },
    runBrowser: async () => 0,
  });

  const running = verification.run();
  await proxyStarted;
  await verification.stop();
  resolveProxy({ stop: async () => { proxyStopCalls += 1; } });

  await assert.rejects(running, /stopped/i);
  assert.equal(proxyStopCalls, 1);
  assert.equal(apiStarts, 0);
});

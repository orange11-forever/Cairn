import assert from "node:assert/strict";
import test from "node:test";

import { runDevCore } from "../../../../scripts/dev-core.mjs";

function deferred() {
  let resolve;
  const promise = new Promise((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function fakeChild(name, completion = Promise.resolve({ code: 0, signal: null })) {
  return {
    name,
    stopCalls: 0,
    stop() {
      this.stopCalls += 1;
    },
    completion,
  };
}

test("dev core bootstraps storage and the embedding profile before managed services", async () => {
  const events = [];
  const environments = [];
  const stop = deferred();
  const result = await runDevCore({
    runTask: async (name) => {
      events.push(`task:${name}`);
      return 0;
    },
    startTask: (name, options) => {
      events.push(`start:${name}`);
      environments.push(options.environment);
      return fakeChild(name);
    },
    waitForUrl: async (url) => events.push(`ready:${url}`),
    announce: () => stop.resolve({ requested: true, signal: "SIGTERM" }),
    termination: stop.promise,
  });

  assert.equal(result, 0);
  assert.deepEqual(events, [
    "task:db:migrate",
    "task:object-store-bootstrap",
    "task:embedding-profile-bootstrap",
    "task:db:seed",
    "start:dev:embedding",
    "ready:http://127.0.0.1:58081/health",
    "start:dev:api",
    "start:dev:worker",
    "start:dev:web",
    "ready:http://127.0.0.1:8080/ready",
    "ready:http://localhost:5500/",
  ]);
  for (const environment of environments) {
    assert.equal(environment.APP_URL, "http://localhost:5500");
    assert.equal(environment.CORS_ORIGINS, "http://localhost:5500");
    assert.equal(environment.VITE_IDENTITY_API_URL, "http://localhost:8080");
    assert.equal(environment.EMBEDDING_BASE_URL, "http://127.0.0.1:58081/v1");
    assert.equal(environment.EMBEDDING_PROVIDER, "local-fake");
    assert.equal(environment.EMBEDDING_DIM, "1024");
    assert.equal(environment.VITE_MOCK_API_URL, undefined);
  }
});

test("bootstrap or seed failure stops before managed services start", async () => {
  const ordered = [
    "db:migrate",
    "object-store-bootstrap",
    "embedding-profile-bootstrap",
    "db:seed",
  ];
  for (const failure of ordered) {
    const tasks = [];
    const starts = [];
    const result = await runDevCore({
      runTask: async (name) => {
        tasks.push(name);
        return name === failure ? 1 : 0;
      },
      startTask: (name) => {
        starts.push(name);
        return fakeChild(name);
      },
      waitForUrl: async () => undefined,
      announce: () => undefined,
      reportError: () => undefined,
    });

    assert.equal(result, 1, failure);
    assert.deepEqual(starts, [], failure);
    assert.deepEqual(tasks, ordered.slice(0, ordered.indexOf(failure) + 1));
  }
});

test("a child failure stops every started sibling", async () => {
  const failed = deferred();
  const never = new Promise(() => undefined);
  const children = [
    fakeChild("dev:embedding", never),
    fakeChild("dev:api", never),
    fakeChild("dev:worker", failed.promise),
    fakeChild("dev:web", never),
  ];
  let started = 0;
  const allStarted = deferred();

  const completion = runDevCore({
    runTask: async () => 0,
    startTask: () => {
      const child = children[started];
      started += 1;
      if (started === children.length) allStarted.resolve();
      return child;
    },
    waitForUrl: async () => undefined,
    announce: () => undefined,
    reportError: () => undefined,
  });

  await allStarted.promise;
  failed.resolve({ code: 1, signal: null });

  assert.equal(await completion, 1);
  assert.deepEqual(children.map((child) => child.stopCalls), [1, 1, 1, 1]);
});

test("readiness failure stops every started service", async () => {
  const children = [
    fakeChild("dev:embedding"),
    fakeChild("dev:api"),
    fakeChild("dev:worker"),
    fakeChild("dev:web"),
  ];
  let started = 0;

  const result = await runDevCore({
    runTask: async () => 0,
    startTask: () => children[started++],
    waitForUrl: async (url) => {
      if (url.endsWith("/ready")) throw new Error("database unavailable");
    },
    announce: () => undefined,
    reportError: () => undefined,
  });

  assert.equal(result, 1);
  assert.deepEqual(children.map((child) => child.stopCalls), [1, 1, 1, 1]);
});

test("termination during fake readiness cleans up without starting Worker", async () => {
  const stop = deferred();
  const children = [];
  const completion = runDevCore({
    runTask: async () => 0,
    startTask: (name) => {
      const child = fakeChild(name, new Promise(() => undefined));
      children.push(child);
      queueMicrotask(() => stop.resolve({ requested: true, signal: "SIGTERM" }));
      return child;
    },
    waitForUrl: async () => new Promise(() => undefined),
    termination: stop.promise,
    announce: () => undefined,
    reportError: () => undefined,
  });
  assert.equal(await completion, 0);
  assert.deepEqual(children.map((child) => child.name), ["dev:embedding"]);
  assert.equal(children[0].stopCalls, 1);
});

test("termination stops the active bootstrap child", async () => {
  const stop = deferred();
  const bootstrap = fakeChild("db:migrate", new Promise(() => undefined));
  const completion = runDevCore({
    startOneShotTask: () => {
      queueMicrotask(() => stop.resolve({ requested: true, signal: "SIGTERM" }));
      return bootstrap;
    },
    startTask: () => { throw new Error("services must not start"); },
    termination: stop.promise,
    announce: () => undefined,
    reportError: () => undefined,
  });
  assert.equal(await completion, 0);
  assert.equal(bootstrap.stopCalls, 1);
});

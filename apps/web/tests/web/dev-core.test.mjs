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

test("dev core migrates and seeds before starting managed services", async () => {
  const events = [];
  const environments = [];
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
    announce: () => undefined,
  });

  assert.equal(result, 0);
  assert.deepEqual(events.slice(0, 5), [
    "task:db:migrate",
    "task:db:seed",
    "start:dev:api",
    "start:mock:web",
    "start:dev:web",
  ]);
  assert.deepEqual(events.slice(5), [
    "ready:http://127.0.0.1:8080/ready",
    "ready:http://localhost:8787/health",
    "ready:http://localhost:5500/",
  ]);
  for (const environment of environments) {
    assert.equal(environment.APP_URL, "http://localhost:5500");
    assert.equal(environment.CORS_ORIGINS, "http://localhost:5500");
    assert.equal(environment.VITE_IDENTITY_API_URL, "http://localhost:8080");
    assert.equal(environment.VITE_MOCK_API_URL, "http://localhost:8787");
  }
});

test("migration or seed failure stops before managed services start", async () => {
  for (const failure of ["db:migrate", "db:seed"]) {
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
    assert.deepEqual(tasks, failure === "db:migrate" ? ["db:migrate"] : ["db:migrate", "db:seed"]);
  }
});

test("a child failure stops every started sibling", async () => {
  const failed = deferred();
  const never = new Promise(() => undefined);
  const children = [
    fakeChild("dev:api", failed.promise),
    fakeChild("mock:web", never),
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
  assert.deepEqual(children.map((child) => child.stopCalls), [1, 1, 1]);
});

test("readiness failure stops every started service", async () => {
  const children = [fakeChild("dev:api"), fakeChild("mock:web"), fakeChild("dev:web")];
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
  assert.deepEqual(children.map((child) => child.stopCalls), [1, 1, 1]);
});

import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";
import * as viteConfig from "../../vite.config.js";

test("registration documents get no-store/no-referrer in dev and preview responses", async () => {
  assert.equal(typeof viteConfig.registrationPagePrivacy, "function");
  for (const hook of ["configureServer", "configurePreviewServer"]) {
    let middleware;
    viteConfig.registrationPagePrivacy()[hook]({ middlewares: { use: value => { middleware = value; } } });
    const server = createServer((request, response) => middleware(request, response, () => response.end("page")));
    await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    const base = `http://127.0.0.1:${server.address().port}`;
    try {
      for (const path of ["/register", "/register/verify", "/register/verify?harmless=1"]) {
        const response = await fetch(base + path);
        assert.equal(response.status, 200);
        assert.equal(response.headers.get("cache-control"), "no-store");
        assert.equal(response.headers.get("referrer-policy"), "no-referrer");
      }
      const unrelated = await fetch(base + "/assets/image.png");
      assert.equal(unrelated.headers.get("cache-control"), null);
    } finally { await new Promise(resolve => server.close(resolve)); }
  }
});

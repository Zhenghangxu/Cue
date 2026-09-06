import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../public/sw.js", import.meta.url), "utf8");

function worker(fetch = async () => new Response("online")) {
  const handlers = {};
  const cached = new Map();
  const deleted = [];
  let claimed = false;
  const cache = {
    add: async (request) => cached.set(request.url, new Response("offline")),
    match: async (url) => cached.get(url)?.clone(),
  };
  vm.runInNewContext(source, {
    self: {
      location: { origin: "http://localhost:3666" },
      addEventListener: (name, handler) => { handlers[name] = handler; },
      clients: { claim: async () => { claimed = true; } },
    },
    caches: {
      open: async () => cache,
      keys: async () => ["cue-offline-v1", "cue-offline-v2", "another-app"],
      delete: async (key) => { deleted.push(key); },
    },
    fetch,
    URL,
    Request: class { constructor(url, options) { this.url = url; this.cache = options.cache; } },
    Response,
  });
  return {
    cached, deleted,
    get claimed() { return claimed; },
    lifecycle(name) {
      let done;
      handlers[name]({ waitUntil: (promise) => { done = promise; } });
      return done;
    },
    request(path = "/", overrides = {}) {
      let result;
      handlers.fetch({
        request: { url: new URL(path, "http://localhost:3666").href, mode: "navigate", method: "GET", ...overrides },
        respondWith: (promise) => { result = promise; },
      });
      return result;
    },
  };
}

test("installation caches only the offline screen; activation only deletes Cue's old caches", async () => {
  const sw = worker();
  await sw.lifecycle("install");
  assert.deepEqual([...sw.cached.keys()], ["/offline.html"]);
  await sw.lifecycle("activate");
  assert.deepEqual(sw.deleted, ["cue-offline-v1"]);
  assert.equal(sw.claimed, true);
});

test("online navigation stays fresh and does not populate the cache", async () => {
  const sw = worker();
  assert.equal(await (await sw.request("/zh/Movies/")).text(), "online");
  assert.equal(sw.cached.size, 0);
});

test("failed navigations and server errors show the cached screen on all routes", async () => {
  for (const fetch of [async () => { throw new TypeError("offline"); }, async () => new Response("unavailable", { status: 503 })]) {
    const sw = worker(fetch);
    await sw.lifecycle("install");
    for (const path of ["/", "/en/", "/zh/Movies/", "/settings/"]) {
      assert.equal(await (await sw.request(path)).text(), "offline");
    }
  }
});

test("API, assets, cross-origin requests, and mutations bypass the worker", () => {
  const sw = worker(() => { throw new Error("must not fetch"); });
  for (const path of ["/api", "/api/settings", "/api/jobs/1/events", "/_next/static/app.js", "https://example.com/"]) {
    assert.equal(sw.request(path), undefined);
  }
  assert.equal(sw.request("/", { method: "POST" }), undefined);
  assert.equal(sw.request("/", { mode: "cors" }), undefined);
});

test("HTTP client errors are preserved; cache eviction still produces a useful fallback", async () => {
  const online = worker(async () => new Response("missing", { status: 404 }));
  assert.equal((await online.request()).status, 404);
  const offline = worker(async () => { throw new TypeError("offline"); });
  const response = await offline.request();
  assert.equal(response.status, 503);
  assert.match(await response.text(), /Start the Cue server/);
});

import assert from "node:assert/strict";
import { test } from "node:test";
import { isAllowedOrigin } from "../src/lib/originGuard.ts";

const host = "localhost:3000";

test("GET is never blocked", () => {
  assert.equal(isAllowedOrigin("GET", { origin: "http://evil.example", host }), true);
});

test("same-origin mutation is allowed", () => {
  assert.equal(isAllowedOrigin("POST", { origin: "http://localhost:3000", host }), true);
  assert.equal(isAllowedOrigin("PATCH", { origin: "http://localhost:3000", host, secFetchSite: "same-origin" }), true);
});

test("cross-origin mutation is blocked", () => {
  assert.equal(isAllowedOrigin("POST", { origin: "http://evil.example", host }), false);
  assert.equal(isAllowedOrigin("POST", { origin: "http://localhost:3001", host }), false);
  assert.equal(isAllowedOrigin("POST", { origin: "null", host }), false);
});

test("browser cross-site fetch without Origin is blocked via Sec-Fetch-Site", () => {
  assert.equal(isAllowedOrigin("POST", { host, secFetchSite: "cross-site" }), false);
  assert.equal(isAllowedOrigin("POST", { host, secFetchSite: "same-site" }), false);
});

test("non-browser client without Origin is allowed", () => {
  assert.equal(isAllowedOrigin("POST", { host }), true);
});

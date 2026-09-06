import assert from "node:assert/strict";
import test from "node:test";
import {
  directoryFromPathname,
  directoryPathname,
  LAST_MEDIA_DIRECTORY_KEY,
  readLastMediaDirectory,
  rememberMediaDirectory,
} from "./directoryRouting.ts";

test("directory URLs round-trip nested paths and special characters in both languages", () => {
  for (const locale of ["en", "zh"]) {
    for (const path of ["", "Movies/Season 1", "中文/#1 & 100%", "settings", "en/Films", "zh", "browse/Movies", "api/files"]) {
      assert.equal(directoryFromPathname(directoryPathname(path, locale)), path);
    }
  }
  assert.equal(directoryPathname("Movies/Season 1", "en"), "/Movies/Season%201/");
  assert.equal(directoryFromPathname("/zh/Movies/"), "Movies");
  assert.equal(directoryFromPathname("/en/Movies"), "Movies");
});

test("rejects malformed URLs and encoded path separators or traversal", () => {
  for (const pathname of ["/%invalid", "/%2e%2e/", "/a%2Fb/", "/a%5Cb/", "/%00/"]) {
    assert.throws(() => directoryFromPathname(pathname));
  }
});

test("remembers a canonical media directory and rejects invalid stored paths", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };

  rememberMediaDirectory(storage, "Movies/Season 1");
  assert.equal(values.get(LAST_MEDIA_DIRECTORY_KEY), "Movies/Season 1");
  assert.equal(readLastMediaDirectory(storage), "Movies/Season 1");

  values.set(LAST_MEDIA_DIRECTORY_KEY, "../private");
  assert.equal(readLastMediaDirectory(storage), "");
});

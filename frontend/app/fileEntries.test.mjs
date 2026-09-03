import assert from "node:assert/strict";
import test from "node:test";
import { filterAndSortEntries } from "./fileEntries.ts";

const entries = [
  { name: "Episode 10", modified: "2026-01-01T00:00:00Z" },
  { name: "Episode 2", modified: "2026-02-01T00:00:00Z" },
  { name: "Bonus", modified: null },
];

test("filters the current entries and sorts by name or date", () => {
  assert.deepEqual(
    filterAndSortEntries(entries, "episode", { key: "modified", direction: "desc" }).map(({ name }) => name),
    ["Episode 2", "Episode 10"],
  );
  assert.deepEqual(
    filterAndSortEntries(entries, "", { key: "name", direction: "asc" }).map(({ name }) => name),
    ["Bonus", "Episode 2", "Episode 10"],
  );
});

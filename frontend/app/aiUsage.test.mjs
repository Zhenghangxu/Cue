import assert from "node:assert/strict";
import test from "node:test";
import { accumulateAiUsage, parseStoredAiUsage } from "./aiUsage.ts";

test("restores persisted AI usage and tolerates invalid data", () => {
  assert.deepEqual(parseStoredAiUsage(null), {
    promptTokens: 0,
    completionTokens: 0,
    totalTokens: 0,
    countedItems: [],
  });
  assert.deepEqual(parseStoredAiUsage("not JSON"), parseStoredAiUsage(null));
  assert.deepEqual(parseStoredAiUsage(JSON.stringify({
    promptTokens: 11,
    completionTokens: 7,
    totalTokens: 18,
    countedItems: ["job-1:0"],
  })), {
    promptTokens: 11,
    completionTokens: 7,
    totalTokens: 18,
    countedItems: ["job-1:0"],
  });
});

test("accumulates each job item exactly once", () => {
  const jobs = [{
    id: "job-1",
    items: [
      { result: { aiUsage: { promptTokens: 11, completionTokens: 7, totalTokens: 18 } } },
      { result: { aiUsage: { promptTokens: 5, completionTokens: 3, totalTokens: 8 } } },
    ],
  }];
  const first = accumulateAiUsage(parseStoredAiUsage(null), jobs);
  const second = accumulateAiUsage(first, jobs);

  assert.deepEqual(first, {
    promptTokens: 16,
    completionTokens: 10,
    totalTokens: 26,
    countedItems: ["job-1:0", "job-1:1"],
  });
  assert.deepEqual(second, first);
});

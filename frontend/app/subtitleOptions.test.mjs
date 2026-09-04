import assert from "node:assert/strict";
import test from "node:test";
import { formatSubtitleModeLabel } from "./subtitleOptions.ts";

test("replaces generic subtitle mode wording with the selected language", () => {
  assert.equal(formatSubtitleModeLabel("Target language only", "Simplified Chinese"), "Simplified Chinese only");
  assert.equal(formatSubtitleModeLabel("English & target language", "Spanish"), "English & Spanish");
});

test("keeps the API label while no language is available", () => {
  assert.equal(formatSubtitleModeLabel("English & target language"), "English & target language");
});

import assert from "node:assert/strict";
import test from "node:test";
import { getSubtitleLanguage } from "./subtitleLanguages.ts";

test("maps detected subtitle languages to accessible country flags", () => {
  assert.deepEqual(getSubtitleLanguage("en"), { flag: "🇬🇧", label: "English" });
  assert.deepEqual(getSubtitleLanguage("zh-tw"), { flag: "🇹🇼", label: "Traditional Chinese" });
  assert.deepEqual(getSubtitleLanguage("zh-cn+en"), {
    flag: "🇨🇳🇬🇧",
    label: "Simplified Chinese & English",
  });
  assert.deepEqual(getSubtitleLanguage(null), { flag: "🏳️", label: "Unknown language" });
});

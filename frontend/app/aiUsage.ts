export type AiUsage = {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
};

type UsageJob = {
  id: string;
  items: Array<{ result?: { aiUsage?: AiUsage } | null }>;
};

export type StoredAiUsage = AiUsage & {
  countedItems: string[];
};

export const AI_USAGE_STORAGE_KEY = "cue-ai-usage";
export const EMPTY_AI_USAGE: AiUsage = {
  promptTokens: 0,
  completionTokens: 0,
  totalTokens: 0,
};

function tokenCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.floor(value)
    : 0;
}

export function parseStoredAiUsage(value: string | null): StoredAiUsage {
  if (!value) return { ...EMPTY_AI_USAGE, countedItems: [] };

  try {
    const stored = JSON.parse(value) as Partial<StoredAiUsage>;
    return {
      promptTokens: tokenCount(stored.promptTokens),
      completionTokens: tokenCount(stored.completionTokens),
      totalTokens: tokenCount(stored.totalTokens),
      countedItems: Array.isArray(stored.countedItems)
        ? stored.countedItems.filter((item): item is string => typeof item === "string")
        : [],
    };
  } catch {
    return { ...EMPTY_AI_USAGE, countedItems: [] };
  }
}

export function accumulateAiUsage(stored: StoredAiUsage, jobs: UsageJob[]): StoredAiUsage {
  const countedItems = new Set(stored.countedItems);
  const next = { ...stored, countedItems: [...stored.countedItems] };

  for (const job of jobs) {
    job.items.forEach((item, index) => {
      const usage = item.result?.aiUsage;
      const itemKey = `${job.id}:${index}`;
      if (!usage || countedItems.has(itemKey)) return;

      next.promptTokens += tokenCount(usage.promptTokens);
      next.completionTokens += tokenCount(usage.completionTokens);
      next.totalTokens += tokenCount(usage.totalTokens);
      countedItems.add(itemKey);
    });
  }

  next.countedItems = [...countedItems];
  return next;
}

export type EntrySort = {
  key: "name" | "modified";
  direction: "asc" | "desc";
};

type NamedEntry = { name: string; modified?: string | null };

export function filterAndSortEntries<T extends NamedEntry>(entries: readonly T[], query: string, sort: EntrySort): T[] {
  const needle = query.trim().toLocaleLowerCase();
  return entries
    .filter(({ name }) => name.toLocaleLowerCase().includes(needle))
    .sort((left, right) => {
      const order = sort.key === "name"
        ? left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" })
        : (Date.parse(left.modified ?? "") || 0) - (Date.parse(right.modified ?? "") || 0);
      return sort.direction === "asc" ? order : -order;
    });
}

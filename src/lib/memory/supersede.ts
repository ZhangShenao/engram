import type { MemoryCandidate, MemoryRecord } from "./types";

/**
 * Resolves which existing memory a candidate should supersede (same type).
 * Phase 1: explicit supersedesMemoryId, else newest active memory of same type.
 */
export function findSupersededMemory(
  candidate: MemoryCandidate,
  existing: MemoryRecord[]
): MemoryRecord | null {
  if (candidate.supersedesMemoryId) {
    const target = existing.find(
      (m) => m.id === candidate.supersedesMemoryId && !m.deletedAt
    );
    if (target) return target;
  }

  const sameType = existing
    .filter(
      (m) =>
        m.type === candidate.type && !m.deletedAt && !m.supersededById
    )
    .sort(
      (a, b) =>
        new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
    );

  if (sameType.length === 0) return null;

  const normalizedNew = candidate.text.toLowerCase().trim();
  const conflict = sameType.find((m) => {
    const old = m.text.toLowerCase().trim();
    return (
      old.includes("name") &&
      normalizedNew.includes("name") &&
      m.type === "fact"
    );
  });

  return conflict ?? sameType[0];
}

export function applySupersede(
  records: MemoryRecord[],
  newId: string,
  supersededId: string
): MemoryRecord[] {
  return records.map((m) =>
    m.id === supersededId
      ? { ...m, supersededById: newId, updatedAt: new Date().toISOString() }
      : m
  );
}

import type { MemoryCandidate, MemoryRecord } from "./types";
import { inferMemorySlot } from "./slots";

/**
 * Returns an existing memory to supersede only on explicit id or same canonical slot.
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

  const slot = candidate.slot ?? inferMemorySlot(candidate.type, candidate.text);
  if (!slot) return null;

  const active = existing.filter((m) => !m.deletedAt && !m.supersededById);
  return (
    active.find((m) => {
      const existingSlot = m.slot ?? inferMemorySlot(m.type, m.text);
      return existingSlot === slot;
    }) ?? null
  );
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

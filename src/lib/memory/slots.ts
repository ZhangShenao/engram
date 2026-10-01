import type { MemoryType } from "./types";

/** Canonical slots where only one active memory may exist at a time. */
export const MEMORY_SLOTS = {
  USER_NAME: "user_name",
} as const;

export type MemorySlot = (typeof MEMORY_SLOTS)[keyof typeof MEMORY_SLOTS];

export function inferMemorySlot(
  type: MemoryType,
  text: string
): MemorySlot | null {
  const lower = text.toLowerCase();
  if (
    type === "fact" &&
    (/\buser'?s name\b/.test(lower) ||
      /\bname is\b/.test(lower) ||
      /\bcalled\b/.test(lower))
  ) {
    return MEMORY_SLOTS.USER_NAME;
  }
  return null;
}

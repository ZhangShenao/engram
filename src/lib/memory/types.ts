export const MEMORY_TYPES = [
  "fact",
  "relationship",
  "promise",
  "boundary",
  "plot",
] as const;

export type MemoryType = (typeof MEMORY_TYPES)[number];

export interface MemoryRecord {
  id: string;
  characterId: string;
  userId: string;
  type: MemoryType;
  text: string;
  salience: number;
  sourceTurnId: string | null;
  supersededById: string | null;
  deletedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface MemoryCandidate {
  type: MemoryType;
  text: string;
  salience: number;
  supersedesMemoryId?: string;
}

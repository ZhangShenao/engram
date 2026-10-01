import type { CharacterCard, ExampleDialogue } from "@/lib/persona/types";
import type { MemoryRecord, MemoryType } from "@/lib/memory/types";

export const LOCAL_USER_ID = "local";

export interface DbCharacterRow {
  id: string;
  name: string;
  tagline: string;
  description: string;
  personality: string;
  scenario: string;
  example_dialogues: string;
  greeting: string;
  speech_style: string;
  boundaries: string;
  created_at: string;
  updated_at: string;
}

export function rowToCharacter(row: DbCharacterRow): CharacterCard {
  return {
    id: row.id,
    name: row.name,
    tagline: row.tagline,
    description: row.description,
    personality: row.personality,
    scenario: row.scenario,
    exampleDialogues: JSON.parse(row.example_dialogues) as ExampleDialogue[],
    greeting: row.greeting,
    speechStyle: row.speech_style,
    boundaries: row.boundaries,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export interface DbMemoryRow {
  id: string;
  character_id: string;
  user_id: string;
  type: string;
  text: string;
  salience: number;
  slot: string | null;
  source_turn_id: string | null;
  superseded_by_id: string | null;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export function rowToMemory(row: DbMemoryRow): MemoryRecord {
  return {
    id: row.id,
    characterId: row.character_id,
    userId: row.user_id,
    type: row.type as MemoryType,
    text: row.text,
    salience: row.salience,
    slot: row.slot ?? null,
    sourceTurnId: row.source_turn_id,
    supersededById: row.superseded_by_id,
    deletedAt: row.deleted_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

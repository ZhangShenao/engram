import Database from "better-sqlite3";
import path from "path";
import fs from "fs";
import { v4 as uuidv4 } from "uuid";
import type { CharacterCard, CharacterInput } from "@/lib/persona/types";
import type { MemoryRecord, MemoryType } from "@/lib/memory/types";
import {
  LOCAL_USER_ID,
  rowToCharacter,
  rowToMemory,
  type DbCharacterRow,
  type DbMemoryRow,
} from "./schema";

const DATA_DIR = path.join(process.cwd(), "data");
const DB_PATH = path.join(DATA_DIR, "roleplay.db");

let db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (db) return db;
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }
  db = new Database(DB_PATH);
  db.pragma("journal_mode = WAL");
  migrate(db);
  return db;
}

function migrate(database: Database.Database) {
  database.exec(`
    CREATE TABLE IF NOT EXISTS characters (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      tagline TEXT NOT NULL,
      description TEXT NOT NULL,
      personality TEXT NOT NULL,
      scenario TEXT NOT NULL,
      example_dialogues TEXT NOT NULL,
      greeting TEXT NOT NULL,
      speech_style TEXT NOT NULL,
      boundaries TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS chat_sessions (
      id TEXT PRIMARY KEY,
      character_id TEXT NOT NULL,
      user_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      UNIQUE(character_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS session_summaries (
      session_id TEXT PRIMARY KEY,
      summary_text TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS memories (
      id TEXT PRIMARY KEY,
      character_id TEXT NOT NULL,
      user_id TEXT NOT NULL,
      type TEXT NOT NULL,
      text TEXT NOT NULL,
      salience REAL NOT NULL,
      source_turn_id TEXT,
      superseded_by_id TEXT,
      deleted_at TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
  `);
  try {
    database.exec(`ALTER TABLE memories ADD COLUMN slot TEXT`);
  } catch {
    /* column exists */
  }
}

export function listCharacters(): CharacterCard[] {
  const rows = getDb()
    .prepare("SELECT * FROM characters ORDER BY updated_at DESC")
    .all() as DbCharacterRow[];
  return rows.map(rowToCharacter);
}

export function getCharacter(id: string): CharacterCard | null {
  const row = getDb()
    .prepare("SELECT * FROM characters WHERE id = ?")
    .get(id) as DbCharacterRow | undefined;
  return row ? rowToCharacter(row) : null;
}

export function createCharacter(input: CharacterInput): CharacterCard {
  const id = uuidv4();
  const now = new Date().toISOString();
  getDb()
    .prepare(
      `INSERT INTO characters (id, name, tagline, description, personality, scenario, example_dialogues, greeting, speech_style, boundaries, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(
      id,
      input.name,
      input.tagline,
      input.description,
      input.personality,
      input.scenario,
      JSON.stringify(input.exampleDialogues),
      input.greeting,
      input.speechStyle,
      input.boundaries,
      now,
      now
    );
  return getCharacter(id)!;
}

export function updateCharacter(
  id: string,
  input: CharacterInput
): CharacterCard | null {
  const now = new Date().toISOString();
  const result = getDb()
    .prepare(
      `UPDATE characters SET name=?, tagline=?, description=?, personality=?, scenario=?, example_dialogues=?, greeting=?, speech_style=?, boundaries=?, updated_at=? WHERE id=?`
    )
    .run(
      input.name,
      input.tagline,
      input.description,
      input.personality,
      input.scenario,
      JSON.stringify(input.exampleDialogues),
      input.greeting,
      input.speechStyle,
      input.boundaries,
      now,
      id
    );
  if (result.changes === 0) return null;
  return getCharacter(id);
}

export function deleteCharacter(id: string): boolean {
  const result = getDb().prepare("DELETE FROM characters WHERE id = ?").run(id);
  return result.changes > 0;
}

export function getOrCreateSession(
  characterId: string,
  userId = LOCAL_USER_ID
): string {
  const existing = getDb()
    .prepare(
      "SELECT id FROM chat_sessions WHERE character_id = ? AND user_id = ?"
    )
    .get(characterId, userId) as { id: string } | undefined;
  if (existing) return existing.id;
  const id = uuidv4();
  const now = new Date().toISOString();
  getDb()
    .prepare(
      "INSERT INTO chat_sessions (id, character_id, user_id, created_at) VALUES (?, ?, ?, ?)"
    )
    .run(id, characterId, userId, now);
  return id;
}

export function listMessages(sessionId: string) {
  return getDb()
    .prepare(
      "SELECT id, role, content, created_at FROM messages WHERE session_id = ? ORDER BY created_at ASC"
    )
    .all(sessionId) as {
    id: string;
    role: "user" | "assistant";
    content: string;
    created_at: string;
  }[];
}

export function insertMessage(
  sessionId: string,
  role: "user" | "assistant",
  content: string
): string {
  const id = uuidv4();
  const now = new Date().toISOString();
  getDb()
    .prepare(
      "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)"
    )
    .run(id, sessionId, role, content, now);
  return id;
}

export function getSummary(sessionId: string): string {
  const row = getDb()
    .prepare("SELECT summary_text FROM session_summaries WHERE session_id = ?")
    .get(sessionId) as { summary_text: string } | undefined;
  return row?.summary_text ?? "";
}

export function appendToSummary(sessionId: string, chunk: string) {
  const prev = getSummary(sessionId);
  const next = prev ? `${prev}\n${chunk}` : chunk;
  const trimmed = next.length > 4000 ? next.slice(-4000) : next;
  const now = new Date().toISOString();
  getDb()
    .prepare(
      `INSERT INTO session_summaries (session_id, summary_text, updated_at) VALUES (?, ?, ?)
       ON CONFLICT(session_id) DO UPDATE SET summary_text=excluded.summary_text, updated_at=excluded.updated_at`
    )
    .run(sessionId, trimmed, now);
}

export function listMemories(
  characterId: string,
  userId = LOCAL_USER_ID
): MemoryRecord[] {
  const rows = getDb()
    .prepare(
      "SELECT * FROM memories WHERE character_id = ? AND user_id = ? ORDER BY updated_at DESC"
    )
    .all(characterId, userId) as DbMemoryRow[];
  return rows.map(rowToMemory);
}

export function listActiveMemories(
  characterId: string,
  userId = LOCAL_USER_ID
): MemoryRecord[] {
  return listMemories(characterId, userId).filter(
    (m) => !m.deletedAt && !m.supersededById
  );
}

export function insertMemory(
  data: Omit<MemoryRecord, "createdAt" | "updatedAt">
): MemoryRecord {
  const now = new Date().toISOString();
  getDb()
    .prepare(
      `INSERT INTO memories (id, character_id, user_id, type, text, salience, slot, source_turn_id, superseded_by_id, deleted_at, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(
      data.id,
      data.characterId,
      data.userId,
      data.type,
      data.text,
      data.salience,
      data.slot,
      data.sourceTurnId,
      data.supersededById,
      data.deletedAt,
      now,
      now
    );
  return { ...data, createdAt: now, updatedAt: now };
}

export function markMemorySuperseded(memoryId: string, byId: string) {
  const now = new Date().toISOString();
  getDb()
    .prepare(
      "UPDATE memories SET superseded_by_id = ?, updated_at = ? WHERE id = ?"
    )
    .run(byId, now, memoryId);
}

export function updateMemory(
  id: string,
  patch: { text?: string; type?: MemoryType; salience?: number }
): MemoryRecord | null {
  const current = getDb()
    .prepare("SELECT * FROM memories WHERE id = ?")
    .get(id) as DbMemoryRow | undefined;
  if (!current || current.deleted_at) return null;
  const now = new Date().toISOString();
  getDb()
    .prepare(
      "UPDATE memories SET text = ?, type = ?, salience = ?, updated_at = ? WHERE id = ?"
    )
    .run(
      patch.text ?? current.text,
      patch.type ?? current.type,
      patch.salience ?? current.salience,
      now,
      id
    );
  const row = getDb()
    .prepare("SELECT * FROM memories WHERE id = ?")
    .get(id) as DbMemoryRow;
  return rowToMemory(row);
}

export function softDeleteMemory(id: string): boolean {
  const now = new Date().toISOString();
  const result = getDb()
    .prepare("UPDATE memories SET deleted_at = ?, updated_at = ? WHERE id = ?")
    .run(now, now, id);
  return result.changes > 0;
}

export function countCharacters(): number {
  const row = getDb()
    .prepare("SELECT COUNT(*) as c FROM characters")
    .get() as { c: number };
  return row.c;
}

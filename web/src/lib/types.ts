export const MEMORY_TYPES = [
  "fact",
  "relationship",
  "promise",
  "boundary",
  "plot",
] as const;

export type MemoryType = (typeof MEMORY_TYPES)[number];

export interface ExampleDialogue {
  user: string;
  assistant: string;
}

export interface Character {
  id: string;
  name: string;
  tagline: string;
  description: string;
  personality: string;
  scenario: string;
  exampleDialogues: ExampleDialogue[];
  greeting: string;
  speechStyle: string;
  boundaries: string;
  createdAt: string;
  updatedAt: string;
}

export type CharacterDraft = Omit<Character, "id" | "createdAt" | "updatedAt">;

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
}

export interface ChatSummary {
  sessionId: string;
  characterId: string;
  name: string;
  tagline: string;
  lastMessage: string;
  updatedAt: string;
}

export interface ContextLayer {
  id: string;
  label: string;
  content: string;
  tokenEstimate: number;
  trimmed: boolean;
  trimReason?: string | null;
}

export interface TurnStage {
  name: string;
  ms: number;
}

export interface TurnTimings {
  orchestrationMs: number;
  modelFirstTokenMs: number | null;
  modelTotalMs: number | null;
  extractMs: number | null;
  stages?: TurnStage[];
}

export interface Inspector {
  layers: ContextLayer[];
  trimLog: string[];
  totalTokens: number;
  budget: number;
  timings?: TurnTimings | null;
}

export interface Memory {
  id: string;
  characterId: string;
  type: MemoryType;
  text: string;
  salience: number;
  slot: string | null;
  deletedAt: string | null;
  supersededById: string | null;
}

export interface ChatPayload {
  sessionId: string;
  character: Character;
  messages: ChatMessage[];
  summary: string;
}

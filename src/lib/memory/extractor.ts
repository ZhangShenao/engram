import type { MemoryCandidate, MemoryType } from "./types";
import { MEMORY_SLOTS } from "./slots";

export interface ExtractorInput {
  userMessage: string;
  assistantMessage: string;
  turnId: string;
}

export interface MemoryExtractor {
  extract(input: ExtractorInput): Promise<MemoryCandidate[]>;
}

/** Deterministic extractor for demo / no API key */
export class DeterministicMemoryExtractor implements MemoryExtractor {
  async extract(input: ExtractorInput): Promise<MemoryCandidate[]> {
    const candidates: MemoryCandidate[] = [];
    const user = input.userMessage.trim();
    const assistant = input.assistantMessage.trim();
    const lower = user.toLowerCase();

    const nameMatch =
      lower.match(/my name is ([\w\s'-]+)/i) ||
      lower.match(/call me ([\w\s'-]+)/i);
    if (nameMatch) {
      candidates.push({
        type: "fact",
        text: `The user's name is ${nameMatch[1].trim()}.`,
        salience: 0.9,
        slot: MEMORY_SLOTS.USER_NAME,
      });
    }

    if (/i promise|i swear|i'll never|i will always/i.test(user)) {
      candidates.push({
        type: "promise",
        text: `User said: "${user.slice(0, 200)}"`,
        salience: 0.75,
      });
    }

    if (/don't ever|never mention|i hate when|boundary/i.test(user)) {
      candidates.push({
        type: "boundary",
        text: `User boundary: ${user.slice(0, 200)}`,
        salience: 0.85,
      });
    }

    if (/we're|we are|you're my|you are my/i.test(user)) {
      candidates.push({
        type: "relationship",
        text: `Relationship note from user: ${user.slice(0, 200)}`,
        salience: 0.7,
      });
    }

    if (/remember that|important:|plot twist|secret is/i.test(user)) {
      candidates.push({
        type: "plot",
        text: user.slice(0, 240),
        salience: 0.65,
      });
    }

    if (candidates.length === 0 && user.length > 20) {
      const factHint = assistant.match(/nice to meet you,?\s+([\w'-]+)/i);
      if (factHint) {
        candidates.push({
          type: "fact",
          text: `The user may be called ${factHint[1]}.`,
          salience: 0.5,
        });
      }
    }

    return candidates;
  }
}

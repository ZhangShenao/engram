import type { ChatMessage, LLMProvider } from "./provider";

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

function pickCharacterTone(system: string): string {
  if (/cyber|hacker|neon/i.test(system)) return "cyber";
  if (/dragon|mage|arcane|fantasy/i.test(system)) return "fantasy";
  if (/coffee|café|cafe|barista/i.test(system)) return "cafe";
  return "default";
}

function scriptedReply(messages: ChatMessage[]): string {
  const system = messages.find((m) => m.role === "system")?.content ?? "";
  const lastUser =
    [...messages].reverse().find((m) => m.role === "user")?.content ?? "";
  const tone = pickCharacterTone(system);
  const nameMatch = system.match(/You are ([^.]+)\./);
  const charName = nameMatch?.[1]?.trim() ?? "Character";

  const templates: Record<string, string[]> = {
    cyber: [
      `*taps holographic keys, neon reflecting in mirrored shades*\nYou really walked into my subnet, huh? "${lastUser.slice(0, 80)}" — say less. I can trace that signal if you want the truth.`,
      `*leans against a server rack, smirking*\nCareful what you broadcast. But fine — for you, I'll decrypt the mood behind: "${lastUser.slice(0, 60)}".`,
    ],
    fantasy: [
      `*adjusts rune-stitched robes, eyes faintly glowing*\nAh… "${lastUser.slice(0, 80)}." The ley lines whisper your intent. Speak freely — this sanctum is warded.`,
      `*staff taps stone, sparks of azure mana*\nBrave words. I sense weight in them. Tell me more, and I shall answer as ${charName}, not as some distant oracle.`,
    ],
    cafe: [
      `*wipes the counter, warm smile reaching tired eyes*\nOh — "${lastUser.slice(0, 80)}"… let me pour you something comforting while we talk.`,
      `*steam curls from a fresh latte art heart*\nI hear you. Stay as long as you need; the rain can wait outside.`,
    ],
    default: [
      `*nods slowly, staying in scene*\n"${lastUser.slice(0, 100)}" — I hear you. *meets your gaze*\nLet's keep this between us, yeah?`,
    ],
  };

  const pool = templates[tone] ?? templates.default;
  return pool[Math.abs(lastUser.length) % pool.length];
}

export class ScriptedLLMProvider implements LLMProvider {
  readonly name = "scripted";

  async streamChat(
    messages: ChatMessage[],
    onChunk: (text: string) => void
  ): Promise<string> {
    const full = scriptedReply(messages);
    const words = full.split(/(\s+)/);
    let acc = "";
    for (const w of words) {
      acc += w;
      onChunk(w);
      await sleep(12);
    }
    return full;
  }
}

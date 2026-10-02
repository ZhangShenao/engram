import asyncio
import os
import re

from engram_contracts.models import ChatMessage


def _pick_tone(system: str) -> str:
    if re.search(r"cyber|hacker|neon", system, flags=re.IGNORECASE):
        return "cyber"
    if re.search(r"dragon|mage|arcane|fantasy", system, flags=re.IGNORECASE):
        return "fantasy"
    if re.search(r"coffee|café|cafe|barista", system, flags=re.IGNORECASE):
        return "cafe"
    return "default"


def scripted_reply(messages: list[ChatMessage]) -> str:
    system = next((message.content for message in messages if message.role == "system"), "")
    last_user = ""
    for message in reversed(messages):
        if message.role == "user":
            last_user = message.content
            break
    tone = _pick_tone(system)
    name_match = re.search(r"You are ([^.]+)\.", system)
    char_name = name_match.group(1).strip() if name_match else "Character"
    templates = {
        "cyber": [
            (
                "*taps holographic keys, neon reflecting in mirrored shades*\n"
                f'You really walked into my subnet, huh? "{last_user[:80]}" — say less. '
                "I can trace that signal if you want the truth."
            ),
            (
                "*leans against a server rack, smirking*\n"
                f'Careful what you broadcast. But fine — for you, I\'ll decrypt the mood behind: "{last_user[:60]}".'
            ),
        ],
        "fantasy": [
            (
                "*adjusts rune-stitched robes, eyes faintly glowing*\n"
                f'Ah… "{last_user[:80]}." The ley lines whisper your intent. '
                "Speak freely — this sanctum is warded."
            ),
            (
                "*staff taps stone, sparks of azure mana*\n"
                "Brave words. I sense weight in them. Tell me more, and I shall answer as "
                f"{char_name}, not as some distant oracle."
            ),
        ],
        "cafe": [
            (
                "*wipes the counter, warm smile reaching tired eyes*\n"
                f'Oh — "{last_user[:80]}"… let me pour you something comforting while we talk.'
            ),
            (
                "*steam curls from a fresh latte art heart*\n"
                "I hear you. Stay as long as you need; the rain can wait outside."
            ),
        ],
        "default": [
            (
                "*nods slowly, staying in scene*\n"
                f'"{last_user[:100]}" — I hear you. *meets your gaze*\n'
                "Let's keep this between us, yeah?"
            ),
        ],
    }
    pool = templates.get(tone, templates["default"])
    return pool[abs(len(last_user)) % len(pool)]


class ScriptedLLMProvider:
    name = "scripted"

    async def iter_chunks(self, messages: list[ChatMessage]):
        delay_ms = float(os.environ.get("SCRIPTED_CHUNK_DELAY_MS", "12"))
        full = scripted_reply(messages)
        for piece in re.split(r"(\s+)", full):
            if piece == "":
                continue
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
            yield piece

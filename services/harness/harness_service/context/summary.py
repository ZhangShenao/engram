from engram_contracts.models import VerbatimTurn


def format_evicted_turns_for_summary(turns: list[VerbatimTurn]) -> str:
    if not turns:
        return ""
    return "\n".join(f"{turn.role}: {turn.content}" for turn in turns)

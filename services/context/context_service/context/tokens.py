import math

DEFAULT_CONTEXT_TOKEN_BUDGET = 4096

LAYER_BUDGET_HINTS = {
    "personaMax": 1200,
    "memoriesMax": 600,
    "summaryMax": 500,
    "turnsMax": 2000,
    "hintMax": 80,
}


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4)

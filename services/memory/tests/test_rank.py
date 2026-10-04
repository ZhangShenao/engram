from datetime import UTC, datetime

from engram_contracts.models import MemoryRecord
from memory_service.domain.rank import (
    effective_salience,
    rank_memories,
    relevance_score,
    should_forget,
)


def mem(**partial) -> MemoryRecord:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    data = {
        "id": partial.pop("id"),
        "characterId": "c",
        "userId": "local",
        "type": "fact",
        "text": "default",
        "salience": 0.5,
        "slot": None,
        "sourceTurnId": None,
        "supersededById": None,
        "deletedAt": None,
        "createdAt": now,
        "updatedAt": now,
    }
    data.update(partial)
    return MemoryRecord.model_validate(data)


def test_ranks_higher_salience_and_relevance():
    ranked = rank_memories(
        [
            mem(id="1", text="User likes coffee", salience=0.3),
            mem(id="2", text="User name is Alex", salience=0.9),
        ],
        "What is my name Alex?",
    )
    assert ranked[0].id == "2"


def test_excludes_deleted_and_superseded():
    ranked = rank_memories(
        [
            mem(id="1", deletedAt=datetime.now(UTC).isoformat()),
            mem(id="2", supersededById="x"),
            mem(id="3", text="active"),
        ],
        "active",
    )
    assert len(ranked) == 1
    assert ranked[0].id == "3"


def test_decay_lowers_old_salience_and_forgets_it_after_the_window():
    old = mem(id="old", text="quiet fact", salience=0.3, createdAt="2026-01-01T00:00:00Z")
    fresh = mem(id="fresh", text="quiet fact", salience=0.3)
    now_ms = 1_769_817_600_000  # thirty days after 2026-01-01
    assert effective_salience(old, now_ms) < effective_salience(fresh, now_ms)
    assert should_forget(old, now_ms) is True
    assert should_forget(fresh, now_ms) is False
    forgotten = old.model_copy(update={"forgotten_at": "2026-01-31T00:00:00Z"})
    ranked = rank_memories([forgotten, fresh], "quiet", now_ms=now_ms)
    assert [item.id for item in ranked] == ["fresh"]


def test_relevance_score_increases_with_overlap():
    assert relevance_score("dragon fire", "ancient dragon breathes fire") > relevance_score(
        "dragon fire", "quiet library"
    )

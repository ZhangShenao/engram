from datetime import datetime, timezone

from engram_contracts.models import MemoryRecord
from memory_service.domain.rank import rank_memories, relevance_score


def mem(**partial) -> MemoryRecord:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
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
            mem(id="1", deletedAt=datetime.now(timezone.utc).isoformat()),
            mem(id="2", supersededById="x"),
            mem(id="3", text="active"),
        ],
        "active",
    )
    assert len(ranked) == 1
    assert ranked[0].id == "3"


def test_relevance_score_increases_with_overlap():
    assert relevance_score("dragon fire", "ancient dragon breathes fire") > relevance_score(
        "dragon fire", "quiet library"
    )

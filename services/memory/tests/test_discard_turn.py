import uuid

from fastapi.testclient import TestClient

from memory_service.main import app
from memory_service.store import connect, get_memory, insert_memory


def _insert(character_id: str, user_id: str, source_turn_id: str, text: str) -> str:
    memory_id = str(uuid.uuid4())
    with connect() as conn:
        insert_memory(
            memory_id,
            character_id,
            user_id,
            "fact",
            text,
            0.6,
            None,
            source_turn_id,
            conn,
        )
    return memory_id


def test_discard_turn_soft_deletes_only_that_source_turn():
    character_id = f"discard-{uuid.uuid4()}"
    user_id = f"user-{uuid.uuid4()}"
    old_turn = f"turn-{uuid.uuid4()}"
    other_turn = f"turn-{uuid.uuid4()}"
    discarded_id = _insert(character_id, user_id, old_turn, "from the discarded reply")
    kept_id = _insert(character_id, user_id, other_turn, "from another turn")
    try:
        with TestClient(app) as client:
            response = client.post("/memories/discard-turn", json={"sourceTurnId": old_turn})
        assert response.status_code == 200
        assert response.json()["discarded"] == 1
        discarded = get_memory(discarded_id)
        kept = get_memory(kept_id)
        assert discarded is not None and discarded.deleted_at
        assert kept is not None and kept.deleted_at is None
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM memories WHERE character_id = %s", (character_id,))

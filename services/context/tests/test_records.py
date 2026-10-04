import json
import uuid

from context_service.inspections import get_inspection, save_inspection
from context_service.inspections import init_db as init_inspections
from context_service.orchestrator import stamp_extract
from context_service.transcript import (
    append_summary,
    delete_by_character,
    ensure_greeting,
    get_pin,
    init_db,
    recent_sessions,
    set_pin,
)


def test_greeting_pin_summary_and_inspection_stamp():
    init_db()
    init_inspections()
    character_id = f"rec-{uuid.uuid4()}"
    try:
        session_id, inserted = ensure_greeting(character_id, "local", "Hello there.")
        assert inserted is True
        again, inserted_again = ensure_greeting(character_id, "local", "Hello there.")
        assert again == session_id
        assert inserted_again is False
        assert get_pin(session_id)[0] == "openrouter"
        set_pin(session_id, "openrouter", "other-model")
        assert get_pin(session_id) == ("openrouter", "other-model")
        summary = append_summary(session_id, "A short beat.")
        assert "short beat" in summary
        chats = recent_sessions("local")
        assert any(chat["sessionId"] == session_id for chat in chats)
        inspection_id = save_inspection(
            character_id,
            "local",
            session_id,
            {"timings": {"extractMs": None, "stages": []}, "layers": []},
        )
        stamp_extract(inspection_id, 12)
        stored = get_inspection(inspection_id)
        assert stored is not None
        assert stored["timings"]["extractMs"] == 12
        assert json.dumps(stored)
    finally:
        delete_by_character(character_id)

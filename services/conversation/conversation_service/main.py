from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from conversation_service.store import (
    add_message,
    append_summary,
    delete_by_character,
    delete_message,
    ensure_session,
    get_summary,
    init_db,
    list_messages,
    recent_sessions,
    session_exists,
)

app = FastAPI(title="Engram Conversation")
init_db()


class EnsureSession(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    character_id: str = Field(alias="characterId")
    user_id: str = Field(alias="userId")


class NewMessage(BaseModel):
    role: str
    content: str


class SummaryAppend(BaseModel):
    text: str


class GreetingBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    character_id: str = Field(alias="characterId")
    user_id: str = Field(alias="userId")
    greeting: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "conversation"}


@app.post("/sessions/ensure")
def post_ensure(body: EnsureSession):
    session_id, created = ensure_session(body.character_id, body.user_id)
    return {"sessionId": session_id, "created": created}


@app.get("/sessions/by-character/{character_id}")
def by_character(character_id: str, userId: str = "local"):
    session_id, _created = ensure_session(character_id, userId)
    return {"sessionId": session_id}


@app.get("/sessions/recent")
def recent(userId: str = "local"):
    return {"chats": recent_sessions(userId)}


@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str):
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"messages": list_messages(session_id)}


@app.post("/sessions/{session_id}/messages", status_code=201)
def post_message(session_id: str, body: NewMessage):
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    if body.role not in {"user", "assistant"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Content is required")
    return {"message": add_message(session_id, body.role, body.content)}


@app.delete("/sessions/{session_id}/messages/{message_id}")
def remove_message(session_id: str, message_id: str):
    if not delete_message(session_id, message_id):
        raise HTTPException(status_code=404, detail="Message not found")
    return {"ok": True}


@app.get("/sessions/{session_id}/summary")
def read_summary(session_id: str):
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"summary": get_summary(session_id)}


@app.post("/sessions/{session_id}/summary/append")
def post_summary(session_id: str, body: SummaryAppend):
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    if not body.text.strip():
        return {"summary": get_summary(session_id)}
    return {"summary": append_summary(session_id, body.text)}


@app.delete("/sessions/by-character/{character_id}")
def remove_character_sessions(character_id: str):
    delete_by_character(character_id)
    return {"ok": True}


@app.post("/internal/ensure-greeting")
def ensure_greeting(body: GreetingBody):
    session_id, _created = ensure_session(body.character_id, body.user_id)
    messages = list_messages(session_id)
    if messages:
        return {"sessionId": session_id, "inserted": False}
    if body.greeting.strip():
        add_message(session_id, "assistant", body.greeting)
    return {"sessionId": session_id, "inserted": bool(body.greeting.strip())}

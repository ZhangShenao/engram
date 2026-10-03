from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryType = Literal["fact", "relationship", "promise", "boundary", "plot"]
MEMORY_TYPES: tuple[str, ...] = (
    "fact",
    "relationship",
    "promise",
    "boundary",
    "plot",
)


class ExampleDialogue(BaseModel):
    user: str
    assistant: str


class CharacterInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    tagline: str = ""
    description: str = ""
    personality: str = ""
    scenario: str = ""
    example_dialogues: list[ExampleDialogue] = Field(default_factory=list, alias="exampleDialogues")
    greeting: str = ""
    speech_style: str = Field(default="", alias="speechStyle")
    boundaries: str = ""


class CharacterCard(CharacterInput):
    id: str
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class MemoryRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    character_id: str = Field(alias="characterId")
    user_id: str = Field(alias="userId")
    type: MemoryType
    text: str
    salience: float
    slot: str | None = None
    source_turn_id: str | None = Field(default=None, alias="sourceTurnId")
    superseded_by_id: str | None = Field(default=None, alias="supersededById")
    deleted_at: str | None = Field(default=None, alias="deletedAt")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")
    score: float | None = None


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: MemoryType
    text: str
    salience: float
    slot: str | None = None
    supersedes_memory_id: str | None = Field(default=None, alias="supersedesMemoryId")


class VerbatimTurn(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ContextLayer(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    label: str
    content: str
    token_estimate: int = Field(alias="tokenEstimate")
    trimmed: bool = False
    trim_reason: str | None = Field(default=None, alias="trimReason")


class AssembledContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    messages: list[ChatMessage]
    layers: list[ContextLayer]
    trim_log: list[str] = Field(alias="trimLog")
    evicted_turns: list[VerbatimTurn] = Field(alias="evictedTurns")
    total_tokens: int = Field(alias="totalTokens")
    budget: int

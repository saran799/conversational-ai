"""Voice API schemas (Worker 1) — exact shapes from docs/API_CONTRACTS.md §3.

The HTTP contract is kept to the documented fields; richer dialogue details
(next action, session state, clarification) live in the internal
DialogueResponse used by the telephony/streaming layer.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from backend.app.schemas.shared import ConversationTurn


class VoiceTurnRequest(BaseModel):
    call_id: str = Field(..., min_length=1, description="Call/session identifier")
    audio_base64: Optional[str] = Field(
        default=None, description="Optional base64-encoded audio chunk (WAV/PCM)"
    )
    text_input: Optional[str] = Field(
        default=None, description="Recognised text (provider-independent dialogue)"
    )
    language_hint: Optional[Literal["ta", "en", "ta-en"]] = Field(
        default=None, description="Language hint from STT or client"
    )

    @model_validator(mode="after")
    def require_text_or_audio(self) -> "VoiceTurnRequest":
        if not (self.text_input and self.text_input.strip()) and not self.audio_base64:
            raise ValueError("Either text_input or audio_base64 must be provided")
        return self


class VoiceTurnResponse(BaseModel):
    turn: ConversationTurn
    suggested_actions: List[str] = Field(default_factory=list)
    response_audio_url: Optional[str] = None
    response_text: str


# Commonized Worker 2 /api/mobility/simulate schemas
class SimulateStopRef(BaseModel):
    stop_id: Optional[str] = None
    name: str


class SimulateLeg(BaseModel):
    mode: str = "bus"
    route: str
    from_stop: SimulateStopRef
    to_stop: SimulateStopRef
    stops_count: int = 1


class SimulateFare(BaseModel):
    status: str = "UNKNOWN"
    reason: Optional[str] = None
    amount_inr: Optional[float] = None


class SimulateDistance(BaseModel):
    value_km: Optional[float] = None
    basis: Optional[str] = None


class SimulateRouteOption(BaseModel):
    legs: List[SimulateLeg] = Field(default_factory=list)
    transfers: int = 0
    ranking_basis: Optional[str] = None
    fare: Optional[SimulateFare] = None
    distance: Optional[SimulateDistance] = None


class SimulateMobilityRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language question spoken by the commuter")
    language: str = Field(default="ta", description="Language code ('ta' for Tamil, 'en' for English)")


class SimulateMobilityResponse(BaseModel):
    status: str = "OK"
    data_status: str = "unverified"
    language: str = "ta"
    speech_text: str
    follow_up_question: Optional[str] = None
    options: List[SimulateRouteOption] = Field(default_factory=list)
    advisories: List[str] = Field(default_factory=list)
    caveats: List[str] = Field(default_factory=list)
    session_id: Optional[str] = None


"""團體四階段與資料物件的固定定義。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


STAGES = ("opening", "formation", "working", "ending")
STAGE_LABELS = {
    "opening": "開始期 Opening",
    "formation": "形成期 Formation",
    "working": "工作期 Working",
    "ending": "結束期 Ending",
}


def next_stage(stage: str) -> str | None:
    try:
        index = STAGES.index(stage)
    except ValueError:
        return None
    return STAGES[index + 1] if index + 1 < len(STAGES) else None


@dataclass
class DialogueTurn:
    role: str
    speaker_id: str
    speaker_name: str
    content: str
    speaker_role: str
    timestamp: str
    stage: str
    message_type: str = "dialogue"
    source: str = "live"
    latency_ms: int | None = None
    error_flag: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class PracticeContext:
    participant_id: str
    session_id: str
    group_series_id: str
    role_mode: str
    group_type: str
    stage: str
    school_id: str
    school_name: str
    base_context: str
    participants: list[dict[str, Any]]
    member_states: dict[str, dict[str, Any]]
    prior_summary: dict[str, Any] = field(default_factory=dict)
    carryover_context: str = ""
    duration_target_minutes: int = 0
    started_at: str = ""
    started_at_epoch: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

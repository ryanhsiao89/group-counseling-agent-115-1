"""團體建立、續談、發言者選擇與逐字稿。"""

from __future__ import annotations

import random
import time
from typing import Any

from .models import DialogueTurn, PracticeContext, STAGE_LABELS
from .personas import find_member, initial_member_states, select_members
from .prompts import APPROACHES
from .utils import new_id, now_iso


AI_LEADER = {
    "id": "ai_leader",
    "name": "AI 團體帶領者",
    "avatar": "🧭",
    "type": "學派示範帶領者",
    "profile": "依學生選擇的學派與團體發展階段示範帶領。",
    "speech_style": "簡潔、尊重、促進成員互動，不在過程中講解技巧。",
}


def create_new_context(
    *,
    participant_id: str,
    role_mode: str,
    group_type: str,
    stage: str,
    school_id: str,
    base_context: str,
    duration_target_minutes: int,
) -> PracticeContext:
    series_id = new_id("series")
    member_count = 3 if role_mode == "leader" else 2
    participants = select_members(member_count, seed=series_id)
    return PracticeContext(
        participant_id=participant_id,
        session_id=new_id("session"),
        group_series_id=series_id,
        role_mode=role_mode,
        group_type=group_type,
        stage=stage,
        school_id=school_id,
        school_name=APPROACHES[school_id]["name"],
        base_context=base_context,
        participants=participants,
        member_states=initial_member_states(participants, stage),
        duration_target_minutes=duration_target_minutes,
        started_at=now_iso(),
        started_at_epoch=time.time(),
    )


def create_continuation_context(
    *,
    participant_id: str,
    saved: dict[str, Any],
    target_stage: str,
    duration_target_minutes: int,
) -> PracticeContext:
    return PracticeContext(
        participant_id=participant_id,
        session_id=new_id("session"),
        group_series_id=str(saved["group_series_id"]),
        role_mode=str(saved["role_mode"]),
        group_type=str(saved["group_type"]),
        stage=target_stage,
        school_id=str(saved["school_id"]),
        school_name=str(saved.get("school_name") or APPROACHES[str(saved["school_id"])]["name"]),
        base_context=str(saved.get("base_context", "")),
        participants=list(saved.get("participants", [])),
        member_states=dict(saved.get("member_states", {})),
        prior_summary=dict(saved.get("prior_summary", {})),
        carryover_context=str(saved.get("carryover_context", "")),
        duration_target_minutes=duration_target_minutes,
        started_at=now_iso(),
        started_at_epoch=time.time(),
    )


def session_start_record(context: PracticeContext, model_name: str, prompt_version: str) -> dict[str, Any]:
    return {
        "event_type": "start",
        "participant_id": context.participant_id,
        "session_id": context.session_id,
        "group_series_id": context.group_series_id,
        "agent_type": "group",
        "role_mode": context.role_mode,
        "group_type": context.group_type,
        "stage": context.stage,
        "school_id": context.school_id,
        "school_name": context.school_name,
        "started_at": context.started_at,
        "model_name": model_name,
        "prompt_version": prompt_version,
        "temperature": 0.4,
        "completion_status": "in_progress",
        "participants_json": context.participants,
        "base_context": context.base_context,
    }


def _last_ai_id(turns: list[dict[str, Any]]) -> str:
    for turn in reversed(turns):
        if str(turn.get("speaker_role", "")).startswith("ai_"):
            return str(turn.get("speaker_id", ""))
    return ""


def choose_speakers(
    context: PracticeContext,
    user_text: str,
    turns: list[dict[str, Any]],
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    rng = rng or random.Random()
    named = find_member(context.participants, user_text)
    if named:
        return [named]

    last_ai = _last_ai_id(turns)
    members = [p for p in context.participants if p["id"] != last_ai] or list(context.participants)

    if context.role_mode == "member":
        if last_ai == "ai_leader" and members:
            primary = rng.choice(members)
        else:
            primary = AI_LEADER if rng.random() < 0.62 else rng.choice(members)
        speakers = [primary]
        if context.stage in {"working", "ending"} and rng.random() < 0.35:
            candidates = [p for p in [AI_LEADER, *context.participants] if p["id"] != primary["id"]]
            speakers.append(rng.choice(candidates))
        return speakers

    primary = rng.choice(members)
    speakers = [primary]
    second_probability = {"opening": 0.05, "formation": 0.18, "working": 0.48, "ending": 0.32}[context.stage]
    if rng.random() < second_probability:
        candidates = [p for p in context.participants if p["id"] != primary["id"]]
        if candidates:
            speakers.append(rng.choice(candidates))
    return speakers


def peer_target(speaker: dict[str, Any], context: PracticeContext, rng: random.Random | None = None) -> str:
    if context.stage not in {"working", "ending"}:
        return ""
    rng = rng or random.Random()
    candidates = [p["name"] for p in context.participants if p["id"] != speaker["id"]]
    if context.role_mode == "member":
        candidates.append("你（學生團體成員）")
    return rng.choice(candidates) if candidates else ""


def add_turn(
    *,
    context: PracticeContext,
    role: str,
    speaker_id: str,
    speaker_name: str,
    speaker_role: str,
    content: str,
    message_type: str = "dialogue",
    source: str = "live",
    latency_ms: int | None = None,
    error_flag: str = "",
) -> dict[str, Any]:
    return DialogueTurn(
        role=role,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        content=content,
        speaker_role=speaker_role,
        timestamp=now_iso(),
        stage=context.stage,
        message_type=message_type,
        source=source,
        latency_ms=latency_ms,
        error_flag=error_flag,
    ).to_dict()


def build_transcript(context: PracticeContext, turns: list[dict[str, Any]]) -> str:
    lines = [
        "【115-1 團體諮商 AI 模擬演練逐字稿】",
        f"匿名代碼：{context.participant_id}",
        f"團體系列：{context.group_series_id}",
        f"本次練習：{context.session_id}",
        f"團體主題：{context.group_type}",
        f"學生角色：{'Leader 團體帶領者' if context.role_mode == 'leader' else 'Member 團體成員'}",
        f"團體階段：{STAGE_LABELS[context.stage]}",
        f"諮商學派：{context.school_name}",
        f"開始時間：{context.started_at}",
        "",
    ]
    for turn in turns:
        if turn.get("speaker_role") == "system":
            lines.append(f"【系統紀錄】{turn.get('content', '')}")
        else:
            lines.append(f"{turn.get('speaker_name', '')}：{turn.get('content', '')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def continuation_label(saved: dict[str, Any]) -> str:
    return (
        f"{saved.get('group_type', '團體')}｜"
        f"上次完成 {STAGE_LABELS.get(str(saved.get('last_completed_stage')), saved.get('last_completed_stage', ''))}｜"
        f"下次 {STAGE_LABELS.get(str(saved.get('next_stage')), saved.get('next_stage', ''))}｜"
        f"{saved.get('school_name', '')}"
    )

"""115-1 團體諮商 AI Agent Streamlit 主程式。"""

from __future__ import annotations

import hashlib
import hmac
import secrets as pysecrets
import time
from typing import Any

import streamlit as st

from src.auth import (
    OtpChallenge,
    generate_otp,
    hash_otp,
    is_allowed_email,
    make_participant_id,
    mask_email,
    send_otp_email,
    verify_otp,
)
from src.config import load_config
from src.data_manager import InMemoryStore, create_store, make_series_state
from src.llm_client import ENGINE_VERSION, GeminiKeyPool, parse_api_keys
from src.models import PracticeContext, STAGE_LABELS, STAGES, next_stage
from src.prompts import (
    APPROACHES,
    build_assessment_prompt,
    build_dialogue_prompts,
    build_stage_summary_prompt,
)
from src.safety import crisis_message, detect_immediate_risk
from src.session_service import (
    AI_LEADER,
    add_turn,
    build_transcript,
    choose_speakers,
    continuation_label,
    create_continuation_context,
    create_new_context,
    peer_target,
    session_start_record,
)
from src.utils import extract_json_object, json_dumps, new_id, now_iso, seconds_since


st.set_page_config(page_title="團體諮商 AI Agent", page_icon="🎭", layout="wide")


def secret_section(name: str) -> dict[str, Any]:
    try:
        value = st.secrets.get(name, {})
        return dict(value) if value else {}
    except Exception:
        return {}


CONFIG = load_config(st.secrets)


@st.cache_resource
def get_store():
    try:
        return create_store(st.secrets), ""
    except Exception as error:
        return InMemoryStore(), str(error)


STORE, STORE_ERROR = get_store()


DEFAULT_STATE = {
    "authenticated": False,
    "verified_email": "",
    "participant_id": "",
    "otp_challenge": None,
    "last_otp_sent_at": 0.0,
    "practice_context": None,
    "turns": [],
    "turn_index": 0,
    "api_pool": None,
    "last_submit_at": 0.0,
    "finished": False,
    "assessment": {},
    "assessment_raw": "",
    "stage_summary": {},
    "stage_summary_raw": "",
    "intro_generated": False,
    "intro_error": "",
    "pending_ai_reply": None,
    "active_model_name": "",
    "last_series_state": None,
}


def init_state() -> None:
    for key, value in DEFAULT_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = value.copy() if isinstance(value, (list, dict)) else value


init_state()


def context_obj() -> PracticeContext:
    return PracticeContext(**st.session_state.practice_context)


def save_context(context: PracticeContext) -> None:
    st.session_state.practice_context = context.to_dict()


def reset_practice() -> None:
    for key in (
        "practice_context", "turns", "turn_index", "api_pool", "last_submit_at", "finished",
        "assessment", "assessment_raw", "stage_summary", "stage_summary_raw", "intro_generated",
        "intro_error", "pending_ai_reply", "active_model_name", "last_series_state",
    ):
        default = DEFAULT_STATE[key]
        st.session_state[key] = default.copy() if isinstance(default, (list, dict)) else default


def logout() -> None:
    st.session_state.clear()
    st.rerun()


def log_turn(context: PracticeContext, turn: dict[str, Any]) -> None:
    st.session_state.turn_index += 1
    record = {
        "session_id": context.session_id,
        "group_series_id": context.group_series_id,
        "participant_id": context.participant_id,
        "turn_index": st.session_state.turn_index,
        "speaker_role": turn["speaker_role"],
        "speaker_id": turn["speaker_id"],
        "speaker_name": turn["speaker_name"],
        "content_raw": turn["content"],
        "timestamp": turn["timestamp"],
        "stage_at_turn": context.stage,
        "school_id": context.school_id,
        "role_mode": context.role_mode,
        "message_type": turn.get("message_type", "dialogue"),
        "source": turn.get("source", "live"),
        "latency_ms": turn.get("latency_ms", ""),
        "error_flag": turn.get("error_flag", ""),
    }
    try:
        STORE.append_turn(record)
    except Exception as error:
        st.toast(f"雲端逐輪紀錄失敗：{error}", icon="⚠️")


def append_and_log(context: PracticeContext, turn: dict[str, Any]) -> None:
    st.session_state.turns.append(turn)
    log_turn(context, turn)


def _member_mode_speakers(
    context: PracticeContext,
    user_text: str,
    turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Member 體驗模式的發言編排：AI Leader 必須持續承擔帶領責任。"""
    lowered = user_text.strip().lower()

    # 學生明確叫 Leader／帶領者時，由 AI Leader 立即接手。
    leader_tokens = ("leader", "ai leader", "帶領者", "團體帶領者", "主持人")
    if any(token in lowered for token in leader_tokens):
        return [AI_LEADER]

    # 學生直接點名某位 AI 成員時：該成員先回應，Leader 隨後統整／串聯。
    named_member = None
    for participant in context.participants:
        name = str(participant.get("name", "")).strip()
        participant_id = str(participant.get("id", "")).strip()
        if (name and name.lower() in lowered) or (participant_id and participant_id.lower() in lowered):
            named_member = participant
            break
    if named_member is not None:
        return [named_member, AI_LEADER]

    # 找上一位 AI 發言者。
    last_ai_id = ""
    for turn in reversed(turns):
        if str(turn.get("speaker_role", "")).startswith("ai_"):
            last_ai_id = str(turn.get("speaker_id", ""))
            break

    # 優先讓「最久沒說話」的 AI 成員取得發言機會，避免固定同一人。
    def recency_score(participant: dict[str, Any]) -> int:
        pid = str(participant.get("id", ""))
        for distance, turn in enumerate(reversed(turns)):
            if str(turn.get("speaker_id", "")) == pid:
                return distance
        return 10**6

    ordered_members = sorted(
        list(context.participants),
        key=recency_score,
        reverse=True,
    )
    candidate = ordered_members[0] if ordered_members else None

    # 若上一位 AI 是 Leader，先讓一位成員說，再由 Leader 收束並繼續帶領。
    if last_ai_id == "ai_leader" and candidate is not None:
        return [candidate, AI_LEADER]

    # 開始期避免一次湧入太多 AI 訊息；Leader 先接住並邀請下一步。
    if context.stage == "opening":
        return [AI_LEADER]

    # 形成／工作／結束期：Leader 先做歷程介入，再邀請一名成員回應，
    # 讓學生能實際體驗成員間互動，而不是多個平行的個別對話。
    if candidate is not None:
        return [AI_LEADER, candidate]
    return [AI_LEADER]


def start_practice(context: PracticeContext, keys: list[str]) -> None:
    reset_practice()
    save_context(context)
    st.session_state.api_pool = GeminiKeyPool(
        keys,
        CONFIG.model_name,
        CONFIG.api_cooldown_seconds,
        getattr(
            CONFIG,
            "fallback_model_names",
            ("gemini-3.5-flash", "gemini-3.1-flash-lite"),
        ),
    )
    st.session_state.active_model_name = CONFIG.model_name
    try:
        STORE.append_session_event(session_start_record(context, CONFIG.model_name, CONFIG.prompt_version))
    except Exception as error:
        st.warning(f"雲端 Session 建立失敗，本次仍可練習：{error}")

    system_text = (
        f"本次為{STAGE_LABELS[context.stage]}；學生角色為"
        f"{'團體帶領者' if context.role_mode == 'leader' else '團體成員'}。"
    )
    system_turn = add_turn(
        context=context,
        role="system",
        speaker_id="system",
        speaker_name="系統",
        speaker_role="system",
        content=system_text,
        message_type="session_start",
        source="system",
    )
    append_and_log(context, system_turn)


def generate_actor_reply(context: PracticeContext, speaker: dict[str, Any], target_peer: str = "") -> None:
    pool: GeminiKeyPool = st.session_state.api_pool

    is_member_mode_leader = context.role_mode == "member" and speaker.get("id") == "ai_leader"
    if is_member_mode_leader and not target_peer:
        # Leader 單獨出現時，優先把話交回學生；若後面排了 AI 成員，
        # 呼叫端會把該成員姓名指定為 target_peer。
        target_peer = "你（學生團體成員）"

    system_prompt, user_prompt = build_dialogue_prompts(
        role_mode=context.role_mode,
        speaker=speaker,
        stage=context.stage,
        approach_id=context.school_id,
        group_type=context.group_type,
        base_context=context.base_context,
        participants=context.participants,
        member_states=context.member_states,
        prior_summary=context.prior_summary,
        carryover_context=context.carryover_context,
        recent_turns=st.session_state.turns[-CONFIG.max_recent_messages :],
        target_peer_name=target_peer,
    )

    if is_member_mode_leader:
        stage_task = {
            "opening": (
                "開始期：主動建立安全感與方向，簡短說明此刻團體要做什麼，"
                "邀請成員自我介紹、表達期待或說出目前最想談的一件事；"
                "注意讓學生與其他成員都有進入團體的機會。"
            ),
            "formation": (
                "形成期：主動注意沉默、觀望、競爭、防衛與參與差異；"
                "適度正常化猶豫，邀請較少發言者，也可詢問不同意見。"
            ),
            "working": (
                "工作期：主動深化核心情緒與此時此刻經驗，辨識共同性、差異、支持或張力，"
                "並促進成員直接回應彼此，而不是所有話都只對 Leader 說。"
            ),
            "ending": (
                "結束期：主動整合本次收穫，邀請彼此回饋、離別或未竟感受，"
                "並連結到團體外可帶走的行動或意義。"
            ),
        }.get(context.stage, "依目前團體階段主動維持團體歷程。")

        system_prompt += f"""

【Member 模式：AI 團體帶領者的主動帶領責任】
你不是等待被點名才說話的成員，而是本團體的帶領者。
每次輪到你，都要先接住上一位發言者的核心內容或情緒，再主動完成至少一項團體歷程工作：
澄清焦點、邀請較少發言者、連結兩位成員的共同／不同經驗、促進成員互相回應、
整理目前團體正在發生的事，或依階段推進下一步。
不要只是回答學生的問題，也不要等學生提醒「Leader 你要不要說些什麼」。
每次以一個清楚焦點為主，避免連珠炮式盤問；通常以一個自然、開放、可回應的邀請收尾。
若指定邀請對象為「{target_peer}」，請讓最後一句自然地把話交給該對象。
若剛才是一位 AI 成員回應學生，請先簡短反映／串聯，再把討論擴回整個團體，而不是重複該成員原話。
本階段特別任務：{stage_task}
""".strip()

    result = pool.generate(system_prompt, user_prompt, temperature=0.4, max_output_tokens=1200)
    st.session_state.active_model_name = result.model_name
    speaker_role = "ai_leader" if speaker["id"] == "ai_leader" else "ai_group_member"
    turn = add_turn(
        context=context,
        role="assistant",
        speaker_id=speaker["id"],
        speaker_name=speaker["name"],
        speaker_role=speaker_role,
        content=result.text,
        latency_ms=result.latency_ms,
        source=f"live:{result.model_name}",
    )
    append_and_log(context, turn)


def safe_finish_practice(context: PracticeContext) -> None:
    transcript = build_transcript(context, st.session_state.turns)
    context_for_model = {
        "role_mode": context.role_mode,
        "group_type": context.group_type,
        "stage": context.stage,
        "school_id": context.school_id,
        "school_name": context.school_name,
        "participants": context.participants,
        "member_states_before": context.member_states,
    }
    pool: GeminiKeyPool = st.session_state.api_pool

    summary_raw = ""
    summary: dict[str, Any] = {}
    summary_model_name = CONFIG.model_name
    try:
        system_prompt, user_prompt = build_stage_summary_prompt(context_for_model, transcript)
        result = pool.generate(system_prompt, user_prompt, temperature=0.0, max_output_tokens=1500)
        summary_model_name = result.model_name
        st.session_state.active_model_name = result.model_name
        summary_raw = result.text
        summary = extract_json_object(summary_raw)
    except Exception as error:
        summary_raw = f"summary_error: {error}"

    if not summary:
        summary = {
            "group_theme": context.group_type,
            "emotional_tone": "目前查不到足夠的模型摘要資料",
            "relationship_state": "請由逐字稿人工檢視",
            "unfinished_issues": [],
            "leader_interventions": [],
            "member_states": context.member_states,
            "carryover_summary": transcript[-CONFIG.max_carryover_chars :],
        }
    if not isinstance(summary.get("member_states"), dict):
        summary["member_states"] = context.member_states

    assessment_raw = ""
    assessment: dict[str, Any] = {}
    assessment_model_name = CONFIG.model_name
    try:
        system_prompt, user_prompt = build_assessment_prompt(context_for_model, transcript)
        result = pool.generate(system_prompt, user_prompt, temperature=0.0, max_output_tokens=1800)
        assessment_model_name = result.model_name
        st.session_state.active_model_name = result.model_name
        assessment_raw = result.text
        assessment = extract_json_object(assessment_raw)
    except Exception as error:
        assessment_raw = f"assessment_error: {error}"
    if not assessment:
        assessment = {
            "feedback_type": "leader_practice" if context.role_mode == "leader" else "member_experience",
            "dimension_scores": {},
            "strengths": [],
            "improvement_points": [],
            "stage_fit": "形成性回饋產生失敗，請以逐字稿進行自我反思或由教師檢視。",
            "approach_fit": "證據不足",
            "next_practice_task": "重新閱讀逐字稿，標記兩句想保留及兩句想改寫的話。",
            "caution": "本回饋僅供形成性學習，不等同標準化成績或專業資格判定。",
        }

    created_at = now_iso()
    try:
        STORE.append_stage_summary({
            "session_id": context.session_id,
            "group_series_id": context.group_series_id,
            "participant_id": context.participant_id,
            "stage": context.stage,
            "group_theme": summary.get("group_theme", ""),
            "emotional_tone": summary.get("emotional_tone", ""),
            "relationship_state": summary.get("relationship_state", ""),
            "unfinished_issues_json": summary.get("unfinished_issues", []),
            "leader_interventions_json": summary.get("leader_interventions", []),
            "member_states_json": summary.get("member_states", {}),
            "carryover_summary": summary.get("carryover_summary", ""),
            "raw_model_output": summary_raw,
            "parsed_json": summary,
            "model_name": summary_model_name,
            "prompt_version": CONFIG.prompt_version,
            "created_at": created_at,
        })
        quoted = []
        for item in assessment.get("strengths", []) + assessment.get("improvement_points", []):
            if isinstance(item, dict) and item.get("quote"):
                quoted.append(item["quote"])
        STORE.append_assessment({
            "session_id": context.session_id,
            "group_series_id": context.group_series_id,
            "participant_id": context.participant_id,
            "role_mode": context.role_mode,
            "stage": context.stage,
            "school_id": context.school_id,
            "rubric_version": CONFIG.rubric_version,
            "dimension_scores_json": assessment.get("dimension_scores", {}),
            "strengths_json": assessment.get("strengths", []),
            "improvement_points_json": assessment.get("improvement_points", []),
            "quoted_examples_json": quoted,
            "stage_fit": assessment.get("stage_fit", ""),
            "approach_fit": assessment.get("approach_fit", ""),
            "next_practice_task": assessment.get("next_practice_task", ""),
            "raw_model_output": assessment_raw,
            "parsed_json": assessment,
            "model_name": assessment_model_name,
            "created_at": created_at,
        })
        STORE.append_session_event({
            **session_start_record(
                context,
                st.session_state.active_model_name or CONFIG.model_name,
                CONFIG.prompt_version,
            ),
            "event_type": "end",
            "ended_at": created_at,
            "duration_seconds": seconds_since(context.started_at_epoch),
            "completion_status": "completed",
        })
        series_state = make_series_state(
            group_series_id=context.group_series_id,
            participant_id=context.participant_id,
            completed_stage=context.stage,
            role_mode=context.role_mode,
            group_type=context.group_type,
            school_id=context.school_id,
            school_name=context.school_name,
            base_context=context.base_context,
            participants=context.participants,
            member_states=summary.get("member_states", context.member_states),
            prior_summary=summary,
            carryover_context=transcript[-CONFIG.max_carryover_chars :],
        )
        STORE.append_series_state(series_state)
        st.session_state.last_series_state = {
            **series_state,
            "participants": context.participants,
            "member_states": summary.get("member_states", context.member_states),
            "prior_summary": summary,
        }
    except Exception as error:
        st.warning(f"雲端結束紀錄未完整寫入：{error}")

    st.session_state.stage_summary = summary
    st.session_state.stage_summary_raw = summary_raw
    st.session_state.assessment = assessment
    st.session_state.assessment_raw = assessment_raw
    st.session_state.finished = True


def render_auth() -> None:
    st.title("🎭 115-1 團體諮商 AI 模擬演練系統")
    st.info("僅供教學演練，不提供心理治療、診斷或緊急危機服務。")
    st.markdown("請使用 `@hcu.edu.tw` 學校 Email 收取一次性驗證碼。教師測試信箱依後台白名單開放。")

    email = st.text_input("學校 Email", placeholder="student@hcu.edu.tw").strip().lower()
    sent_elapsed = time.time() - float(st.session_state.last_otp_sent_at or 0)
    resend_wait = max(0, CONFIG.otp_resend_seconds - int(sent_elapsed))

    if st.button("寄送 6 位數驗證碼", type="primary", disabled=bool(st.session_state.last_otp_sent_at and resend_wait > 0)):
        if not is_allowed_email(email, CONFIG.allowed_domain, CONFIG.teacher_test_emails):
            st.error(f"請使用 @{CONFIG.allowed_domain} 信箱；未列入白名單的外部信箱無法登入。")
        else:
            otp = generate_otp()
            nonce = pysecrets.token_hex(16)
            try:
                with st.spinner("正在寄送驗證碼…"):
                    send_otp_email(email, otp, secret_section("email"))
                challenge = OtpChallenge(email, hash_otp(otp, nonce), nonce, time.time())
                st.session_state.otp_challenge = challenge.__dict__
                st.session_state.last_otp_sent_at = time.time()
                st.success(f"驗證碼已寄到 {mask_email(email)}。")
                st.rerun()
            except Exception as error:
                st.error(f"驗證信寄送失敗：{error}")

    if st.session_state.last_otp_sent_at and resend_wait > 0:
        st.caption(f"約 {resend_wait} 秒後可重新寄送。")

    raw_challenge = st.session_state.otp_challenge
    if raw_challenge:
        challenge = OtpChallenge(**raw_challenge)
        otp_input = st.text_input("輸入驗證碼", type="password", max_chars=6)
        if st.button("確認登入"):
            if challenge.expired(CONFIG.otp_expiry_seconds):
                st.error("驗證碼已過期，請重新寄送。")
                st.session_state.otp_challenge = None
            elif challenge.attempts >= CONFIG.otp_max_attempts:
                st.error("錯誤次數已達上限，請重新寄送驗證碼。")
                st.session_state.otp_challenge = None
            elif verify_otp(otp_input, challenge.otp_hash, challenge.nonce):
                st.session_state.authenticated = True
                st.session_state.verified_email = challenge.email
                st.session_state.participant_id = make_participant_id(challenge.email, CONFIG.participant_salt)
                st.session_state.otp_challenge = None
                st.rerun()
            else:
                challenge.attempts += 1
                st.session_state.otp_challenge = challenge.__dict__
                st.error(f"驗證碼錯誤；剩餘 {CONFIG.otp_max_attempts - challenge.attempts} 次。")


GROUP_TYPES = [
    "大學生生涯探索團體",
    "人際關係成長團體",
    "情緒支持團體",
    "壓力調適與自我照顧團體",
    "憤怒情緒管理團體",
    "哀傷與失落輔導團體",
    "職場／學校溝通技巧團體",
    "其他（自訂）",
]


DEFAULT_CONTEXTS = [
    "成員剛進入團體，彼此還不熟悉，願意參與但等待清楚而不具壓迫性的邀請。",
    "成員近期在人際、課業與未來方向上各有壓力，希望從彼此經驗得到理解。",
    "團體氣氛大致平穩，但成員的參與速度與表達方式不同，需要兼顧安全與互動。",
]


def render_setup() -> None:
    st.title("建立本次團體練習")
    st.caption(f"已完成 Email 驗證｜匿名代碼：{st.session_state.participant_id}")
    if not STORE.persistent:
        detail = f"（{STORE_ERROR}）" if STORE_ERROR else ""
        st.warning(f"Google Sheets 尚未連線{detail}。本次可測試，但跨瀏覽器續談與永久紀錄不會保存。")

    try:
        continuations = STORE.continuations_for(st.session_state.participant_id)
    except Exception as error:
        continuations = []
        st.warning(f"目前無法讀取既有續談：{error}")

    choice_options = ["開始新的團體"] + (["續談既有團體"] if continuations else [])
    action = st.radio("這次要怎麼練習？", choice_options, horizontal=True)

    api_key_raw = st.text_area(
        "你的 Gemini API Key",
        height=80,
        placeholder="可貼 1–2 把；多把請用逗號或換行分隔",
        help="只暫存在目前瀏覽器 Session，不會寫入 Google Sheets 或逐字稿。",
    )
    passcode = st.text_input("課程通行碼", type="password") if CONFIG.course_passcode else ""
    duration_label = st.selectbox("建議練習時間（不強制中斷）", ["不鎖時間", "8 分鐘", "10 分鐘"], index=2)
    duration_minutes = {"不鎖時間": 0, "8 分鐘": 8, "10 分鐘": 10}[duration_label]

    selected_saved = None
    if action == "續談既有團體":
        labels = [continuation_label(item) for item in continuations]
        selected_label = st.selectbox("選擇要接續的團體", labels)
        selected_saved = continuations[labels.index(selected_label)]
        recommended = str(selected_saved.get("next_stage", "formation"))
        allowed_stages = list(STAGES[STAGES.index(recommended) :])
        target_stage = st.selectbox(
            "本次接續階段",
            allowed_stages,
            format_func=lambda value: STAGE_LABELS[value],
            help="建議依序進行；若跳階段，系統仍會帶入前次摘要與同一批成員。",
        )
        st.info(
            f"將沿用：{selected_saved.get('group_type')}｜"
            f"{'Leader' if selected_saved.get('role_mode') == 'leader' else 'Member'}｜"
            f"{selected_saved.get('school_name')}"
        )
        role_mode = str(selected_saved.get("role_mode"))
        group_type = str(selected_saved.get("group_type"))
        school_id = str(selected_saved.get("school_id"))
        base_context = str(selected_saved.get("base_context", ""))
    else:
        col1, col2 = st.columns(2)
        with col1:
            role_label = st.radio(
                "學生角色",
                ["Leader：練習帶領團體", "Member：體驗學派團體"],
                help="Leader 模式由你帶領三名 AI 成員；Member 模式由 AI Leader 帶領你與兩名 AI 成員。",
            )
            role_mode = "leader" if role_label.startswith("Leader") else "member"
            selected_group = st.selectbox("團體主題", GROUP_TYPES)
            group_type = st.text_input("自訂團體名稱").strip() if selected_group == "其他（自訂）" else selected_group
            target_stage = st.selectbox("本次團體階段", STAGES, format_func=lambda value: STAGE_LABELS[value])
        with col2:
            school_names = [item["name"] for item in APPROACHES.values()]
            selected_school_name = st.selectbox("諮商學派", school_names)
            school_id = next(key for key, item in APPROACHES.items() if item["name"] == selected_school_name)
            st.caption("本學派的核心技巧：" + "、".join(APPROACHES[school_id]["techniques"]))
            base_context = st.text_area(
                "前情提要／團體氣氛（可留白）",
                placeholder="請勿輸入真實個案姓名、電話、地址、學號或可辨識機構資訊。",
            ).strip()
            if not base_context:
                base_context = DEFAULT_CONTEXTS[0]

    consent = st.checkbox("我了解這是教學模擬，且不會輸入可識別的真實個案資料。")
    if st.button("開始本次練習", type="primary", use_container_width=True):
        keys = parse_api_keys(api_key_raw)
        if not keys:
            st.error("請輸入至少一把 Gemini API Key。")
            return
        if CONFIG.course_passcode and not hmac.compare_digest(passcode, CONFIG.course_passcode):
            st.error("課程通行碼不正確。")
            return
        if not group_type:
            st.error("請填寫團體名稱。")
            return
        if not consent:
            st.error("請先閱讀並勾選資料與教學用途提醒。")
            return

        if selected_saved:
            context = create_continuation_context(
                participant_id=st.session_state.participant_id,
                saved=selected_saved,
                target_stage=target_stage,
                duration_target_minutes=duration_minutes,
            )
        else:
            context = create_new_context(
                participant_id=st.session_state.participant_id,
                role_mode=role_mode,
                group_type=group_type,
                stage=target_stage,
                school_id=school_id,
                base_context=base_context,
                duration_target_minutes=duration_minutes,
            )
        start_practice(context, keys)
        st.rerun()


def render_feedback(context: PracticeContext) -> None:
    assessment = st.session_state.assessment
    st.success("本階段已完成，逐字稿、階段摘要與形成性回饋已送出。")
    transcript = build_transcript(context, st.session_state.turns)
    filename = (
        f"GroupCounseling_{context.role_mode}_{context.stage}_"
        f"{context.school_id}_{now_iso()[:10].replace('-', '')}.txt"
    )
    st.download_button(
        "📥 下載本次練習逐字稿",
        data=transcript.encode("utf-8-sig"),
        file_name=filename,
        mime="text/plain",
        use_container_width=True,
    )

    if CONFIG.show_feedback_to_students:
        st.subheader("形成性回饋")
        scores = assessment.get("dimension_scores", {})
        if isinstance(scores, dict) and scores:
            columns = st.columns(min(3, len(scores)))
            for index, (name, value) in enumerate(scores.items()):
                columns[index % len(columns)].metric(name, f"{value} / 5")
        st.markdown(f"**階段適配：** {assessment.get('stage_fit', '證據不足')}")
        st.markdown(f"**學派契合：** {assessment.get('approach_fit', '證據不足')}")
        strengths = assessment.get("strengths", [])
        if strengths:
            st.markdown("**做得好的地方**")
            for item in strengths:
                if isinstance(item, dict):
                    st.write(f"- {item.get('point', '')}（原句：{item.get('quote', '證據不足')}）")
        improvements = assessment.get("improvement_points", [])
        if improvements:
            st.markdown("**最值得調整的地方**")
            for item in improvements:
                if isinstance(item, dict):
                    st.write(
                        f"- {item.get('point', '')}（原句：{item.get('quote', '證據不足')}）"
                        f"\n\n  可嘗試：{item.get('alternative', '')}"
                    )
        st.markdown(f"**下一次練習任務：** {assessment.get('next_practice_task', '')}")
        st.caption(assessment.get("caution", "本回饋僅供形成性學習，不等同標準化成績。"))
    else:
        st.info("形成性評量已保存供教師檢視；本課程設定不在學生端顯示。")

    upcoming = next_stage(context.stage)
    col1, col2, col3 = st.columns(3)
    if upcoming and st.session_state.last_series_state:
        if col1.button(f"接著進入 {STAGE_LABELS[upcoming]}", type="primary", use_container_width=True):
            saved = st.session_state.last_series_state
            keys = list(st.session_state.api_pool.api_keys)
            continued = create_continuation_context(
                participant_id=context.participant_id,
                saved=saved,
                target_stage=upcoming,
                duration_target_minutes=context.duration_target_minutes,
            )
            start_practice(continued, keys)
            st.rerun()
    if col2.button("返回練習設定", use_container_width=True):
        reset_practice()
        st.rerun()
    if col3.button("登出", use_container_width=True):
        logout()


def render_practice() -> None:
    context = context_obj()
    if st.session_state.finished:
        render_feedback(context)
        return

    with st.sidebar:
        st.header("本次練習")
        st.write(f"**角色：** {'Leader' if context.role_mode == 'leader' else 'Member'}")
        st.write(f"**階段：** {STAGE_LABELS[context.stage]}")
        st.write(f"**學派：** {context.school_name}")
        active_model = st.session_state.active_model_name or CONFIG.model_name
        st.caption(f"目前模型：{active_model}")
        st.caption(f"AI 引擎版本：{ENGINE_VERSION}")
        if active_model != CONFIG.model_name:
            st.info("主要模型忙碌，系統已自動切換備援模型，練習可繼續。")
        elapsed = seconds_since(context.started_at_epoch)
        st.metric("已進行", f"{elapsed // 60:02d}:{elapsed % 60:02d}")
        if context.duration_target_minutes:
            target_seconds = context.duration_target_minutes * 60
            st.progress(min(1.0, elapsed / target_seconds))
            if elapsed >= target_seconds:
                st.info("已達建議練習時間；可繼續，或結束並查看回饋。")
        transcript = build_transcript(context, st.session_state.turns)
        st.download_button(
            "下載目前逐字稿備份",
            data=transcript.encode("utf-8-sig"),
            file_name=f"GroupCounseling_backup_{context.stage}.txt",
            mime="text/plain",
            use_container_width=True,
        )
        if st.button("結束本階段並查看回饋", type="primary", use_container_width=True):
            with st.spinner("正在整理階段摘要與形成性回饋…"):
                safe_finish_practice(context)
            st.rerun()
        if st.button("放棄本次並返回設定", use_container_width=True):
            try:
                STORE.append_session_event({
                    **session_start_record(context, CONFIG.model_name, CONFIG.prompt_version),
                    "event_type": "end",
                    "ended_at": now_iso(),
                    "duration_seconds": seconds_since(context.started_at_epoch),
                    "completion_status": "abandoned",
                })
            except Exception:
                pass
            reset_practice()
            st.rerun()

    st.title(f"💬 {context.group_type}")
    st.caption(
        f"{STAGE_LABELS[context.stage]}｜"
        f"{'你是團體帶領者' if context.role_mode == 'leader' else '你是團體成員'}｜"
        f"{context.school_name}"
    )
    st.info("請勿輸入真實個案的姓名、電話、地址、學號或可辨識的學校／公司資訊。")

    display_people = context.participants if context.role_mode == "leader" else [AI_LEADER, *context.participants]
    columns = st.columns(len(display_people))
    for index, person in enumerate(display_people):
        with columns[index]:
            st.markdown(f"### {person['avatar']} {person['name']}")
            st.caption(person["type"])

    for turn in st.session_state.turns:
        if turn["speaker_role"] == "system":
            st.caption(f"系統：{turn['content']}")
            continue
        is_student = turn["speaker_role"].startswith("student_")
        avatar = "🧑‍🏫" if context.role_mode == "leader" else "🧑"
        if not is_student:
            person = next((p for p in display_people if p["id"] == turn["speaker_id"]), None)
            avatar = person.get("avatar", "🤖") if person else "🤖"
        with st.chat_message("user" if is_student else "assistant", avatar=avatar):
            st.markdown(f"**{turn['speaker_name']}：** {turn['content']}")

    if context.role_mode == "member" and not st.session_state.intro_generated:
        intro_status = st.empty()
        retry_intro = not st.session_state.intro_error
        if st.session_state.intro_error:
            intro_status.warning(
                f"AI 團體帶領者暫時無法開場：{st.session_state.intro_error}"
            )
            retry_intro = st.button(
                "重新嘗試 AI 開場",
                type="primary",
                key="retry_ai_leader_intro",
            )

        if retry_intro:
            try:
                with st.spinner("團體帶領者正在開場…"):
                    generate_actor_reply(context, AI_LEADER)
                st.session_state.intro_generated = True
                st.session_state.intro_error = ""
                st.rerun()
            except Exception as error:
                st.session_state.intro_error = str(error)
                intro_status.warning(f"AI 團體帶領者暫時無法開場：{error}")

    pending_reply = st.session_state.pending_ai_reply
    if pending_reply:
        pending_speaker = dict(pending_reply.get("speaker", {}))
        pending_name = pending_speaker.get("name", "AI 成員")
        st.warning(
            f"{pending_name} 上一次暫時無法回應："
            f"{pending_reply.get('error', 'Gemini 服務暫時忙碌')}"
        )
        if st.button(
            f"重新嘗試 {pending_name} 回應",
            type="primary",
            key="retry_pending_ai_reply",
        ):
            try:
                with st.spinner(f"{pending_name} 正在重新回應…"):
                    generate_actor_reply(
                        context,
                        pending_speaker,
                        str(pending_reply.get("target_peer", "")),
                    )
                st.session_state.pending_ai_reply = None
                st.rerun()
            except Exception as error:
                pending_reply["error"] = str(error)
                st.session_state.pending_ai_reply = pending_reply
                st.warning(f"仍無法取得回應：{error}")
        st.caption("請先完成這次重試，再繼續輸入，以維持團體對話順序。")
        return

    cooldown_left = max(0, CONFIG.input_cooldown_seconds - int(time.time() - st.session_state.last_submit_at))
    if cooldown_left > 0:
        st.caption(f"請稍候約 {cooldown_left} 秒再送出下一段。")
    user_input = st.chat_input(f"輸入你的回應（最多 {CONFIG.max_user_input_chars} 字）")
    if user_input:
        text = user_input.strip()
        if not text:
            return
        if len(text) > CONFIG.max_user_input_chars:
            st.warning(f"目前共 {len(text)} 字，請縮短至 {CONFIG.max_user_input_chars} 字以內。")
            return
        if cooldown_left > 0:
            st.warning(f"請稍候約 {cooldown_left} 秒再送出。")
            return

        student_role = "student_leader" if context.role_mode == "leader" else "student_member"
        student_name = "Student Leader" if context.role_mode == "leader" else "Student Member"
        student_turn = add_turn(
            context=context,
            role="user",
            speaker_id=context.participant_id,
            speaker_name=student_name,
            speaker_role=student_role,
            content=text,
            message_type="student_message",
        )
        append_and_log(context, student_turn)
        st.session_state.last_submit_at = time.time()

        if detect_immediate_risk(text):
            safety_turn = add_turn(
                context=context,
                role="system",
                speaker_id="system",
                speaker_name="安全提示",
                speaker_role="system",
                content=crisis_message(),
                message_type="safety_escalation",
                source="system",
                error_flag="immediate_risk_keyword",
            )
            append_and_log(context, safety_turn)
            st.rerun()

        if context.role_mode == "member":
            speakers = _member_mode_speakers(context, text, st.session_state.turns)
        else:
            speakers = choose_speakers(context, text, st.session_state.turns)

        for speaker_index, speaker in enumerate(speakers):
            if context.role_mode == "member" and speaker.get("id") == "ai_leader":
                if speaker_index + 1 < len(speakers):
                    target_peer = str(speakers[speaker_index + 1].get("name", "")).strip()
                else:
                    target_peer = "你（學生團體成員）"
            else:
                target_peer = peer_target(speaker, context)
            try:
                with st.spinner(f"{speaker['name']} 正在回應…"):
                    generate_actor_reply(context, speaker, target_peer)
            except Exception as error:
                error_turn = add_turn(
                    context=context,
                    role="system",
                    speaker_id="system",
                    speaker_name="系統",
                    speaker_role="system",
                    content=f"{speaker['name']} 回應失敗：{error}",
                    message_type="ai_error",
                    source="system",
                    error_flag=str(error),
                )
                append_and_log(context, error_turn)
                st.session_state.pending_ai_reply = {
                    "speaker": dict(speaker),
                    "target_peer": target_peer,
                    "error": str(error),
                }
                break
        st.rerun()


with st.sidebar:
    st.caption("本系統僅供教學模擬。")
    if st.session_state.authenticated and st.button("登出目前帳號"):
        logout()

if not st.session_state.authenticated:
    render_auth()
elif st.session_state.practice_context is None:
    render_setup()
else:
    render_practice()

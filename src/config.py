"""集中管理程式預設值與 Streamlit Secrets。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class AppConfig:
    app_title: str = "115-1 團體諮商 AI 模擬演練系統"
    model_name: str = "gemini-2.5-flash"
    prompt_version: str = "group-v1.0.0"
    rubric_version: str = "group-rubric-v1.0.0"
    allowed_domain: str = "hcu.edu.tw"
    teacher_test_emails: tuple[str, ...] = ()
    participant_salt: str = "CHANGE-ME-IN-SECRETS"
    course_passcode: str = ""
    otp_expiry_seconds: int = 600
    otp_resend_seconds: int = 60
    otp_max_attempts: int = 5
    api_cooldown_seconds: int = 90
    input_cooldown_seconds: int = 3
    max_user_input_chars: int = 300
    max_recent_messages: int = 16
    max_carryover_chars: int = 5000
    show_feedback_to_students: bool = True


def _section(secrets: Mapping[str, Any] | None, key: str) -> Mapping[str, Any]:
    if secrets is None:
        return {}
    try:
        value = secrets.get(key, {})
        return dict(value) if value else {}
    except Exception:
        return {}


def load_config(secrets: Mapping[str, Any] | None = None) -> AppConfig:
    raw = _section(secrets, "app")
    emails = raw.get("teacher_test_emails", [])
    if isinstance(emails, str):
        emails = [item.strip() for item in emails.split(",") if item.strip()]

    return AppConfig(
        app_title=str(raw.get("app_title", AppConfig.app_title)),
        model_name=str(raw.get("model_name", AppConfig.model_name)),
        prompt_version=str(raw.get("prompt_version", AppConfig.prompt_version)),
        rubric_version=str(raw.get("rubric_version", AppConfig.rubric_version)),
        allowed_domain=str(raw.get("allowed_domain", AppConfig.allowed_domain)).lower().lstrip("@"),
        teacher_test_emails=tuple(str(x).strip().lower() for x in emails),
        participant_salt=str(raw.get("participant_salt", AppConfig.participant_salt)),
        course_passcode=str(raw.get("course_passcode", "")),
        otp_expiry_seconds=int(raw.get("otp_expiry_seconds", AppConfig.otp_expiry_seconds)),
        otp_resend_seconds=int(raw.get("otp_resend_seconds", AppConfig.otp_resend_seconds)),
        otp_max_attempts=int(raw.get("otp_max_attempts", AppConfig.otp_max_attempts)),
        api_cooldown_seconds=int(raw.get("api_cooldown_seconds", AppConfig.api_cooldown_seconds)),
        input_cooldown_seconds=int(raw.get("input_cooldown_seconds", AppConfig.input_cooldown_seconds)),
        max_user_input_chars=int(raw.get("max_user_input_chars", AppConfig.max_user_input_chars)),
        max_recent_messages=int(raw.get("max_recent_messages", AppConfig.max_recent_messages)),
        max_carryover_chars=int(raw.get("max_carryover_chars", AppConfig.max_carryover_chars)),
        show_feedback_to_students=bool(raw.get("show_feedback_to_students", True)),
    )

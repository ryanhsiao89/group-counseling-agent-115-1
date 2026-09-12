"""Email 驗證、OTP 與匿名 participant_id。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import smtplib
import time
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Any, Mapping


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_allowed_email(email: str, allowed_domain: str, teacher_test_emails: tuple[str, ...]) -> bool:
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        return False
    domain = allowed_domain.lower().lstrip("@")
    return normalized.endswith(f"@{domain}") or normalized in set(teacher_test_emails)


def make_participant_id(email: str, salt: str) -> str:
    digest = hmac.new(
        salt.encode("utf-8"),
        normalize_email(email).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"P_{digest[:16]}"


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str, nonce: str) -> str:
    return hmac.new(nonce.encode("utf-8"), otp.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_otp(candidate: str, expected_hash: str, nonce: str) -> bool:
    return hmac.compare_digest(hash_otp(candidate.strip(), nonce), expected_hash)


@dataclass
class OtpChallenge:
    email: str
    otp_hash: str
    nonce: str
    issued_at: float
    attempts: int = 0

    def expired(self, expiry_seconds: int, now: float | None = None) -> bool:
        return (now or time.time()) - self.issued_at > expiry_seconds


def mask_email(email: str) -> str:
    local, _, domain = normalize_email(email).partition("@")
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}***@{domain}"


def send_otp_email(receiver_email: str, otp: str, email_settings: Mapping[str, Any]) -> None:
    sender_email = str(email_settings.get("sender_email", "")).strip()
    app_password = str(email_settings.get("app_password", "")).replace(" ", "").strip()
    if not sender_email or not app_password:
        raise RuntimeError("尚未設定寄件 Gmail 與 App Password。")

    body = (
        "您好：\n\n"
        "歡迎使用 115-1 團體諮商 AI 模擬演練系統。\n\n"
        f"您的 6 位數登入驗證碼是：{otp}\n\n"
        "驗證碼約 10 分鐘內有效。若非您本人操作，請忽略此信。\n"
        "本系統僅供教學演練，不提供心理治療或緊急危機服務。"
    )
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = "團體諮商 AI Agent 登入驗證碼"
    message["From"] = sender_email
    message["To"] = receiver_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
        server.login(sender_email, app_password)
        server.send_message(message)

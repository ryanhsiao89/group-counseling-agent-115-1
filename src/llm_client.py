"""Google GenAI SDK 包裝、金鑰輪替與錯誤分類。"""

from __future__ import annotations

import time
from dataclasses import dataclass


def parse_api_keys(raw: str) -> list[str]:
    normalized = raw.replace("，", ",").replace("\n", ",")
    keys = []
    for item in normalized.split(","):
        key = item.strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def is_quota_error(error: Exception) -> bool:
    text = str(error).lower()
    return any(x in text for x in ("429", "quota", "resource_exhausted", "resource exhausted", "rate limit"))


def is_invalid_key_error(error: Exception) -> bool:
    text = str(error).lower()
    return any(x in text for x in ("api_key_invalid", "api key not valid", "invalid api key", "permission_denied"))


def is_transient_service_error(error: Exception) -> bool:
    """辨識適合稍後重試的 Gemini 暫時性服務錯誤。"""
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "408",
            "500",
            "502",
            "503",
            "504",
            "unavailable",
            "high demand",
            "service unavailable",
            "temporarily unavailable",
            "timeout",
            "timed out",
            "connection reset",
        )
    )


@dataclass
class GenerationResult:
    text: str
    key_index: int
    latency_ms: int


class GeminiKeyPool:
    def __init__(self, api_keys: list[str], model_name: str, cooldown_seconds: int = 90):
        if not api_keys:
            raise ValueError("至少需要一把 Gemini API Key。")
        self.api_keys = api_keys
        self.model_name = model_name
        self.cooldown_seconds = cooldown_seconds
        self.current_index = 0
        self.blocked_until = 0.0

    def _generate_once(
        self,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_output_tokens: int,
    ) -> str:
        from google import genai

        client = genai.Client(api_key=api_key)
        try:
            from google.genai import types

            response = client.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ),
            )
            text = getattr(response, "text", "")
        except AttributeError:
            interaction = client.interactions.create(
                model=self.model_name,
                input=user_prompt,
                system_instruction=system_prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                },
            )
            text = getattr(interaction, "output_text", "")
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        return str(text or "").strip()

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.4,
        max_output_tokens: int = 700,
    ) -> GenerationResult:
        if time.time() < self.blocked_until:
            wait = int(self.blocked_until - time.time()) + 1
            raise RuntimeError(f"Gemini 暫時達到流量限制，請約 {wait} 秒後再試。")

        last_error: Exception | None = None
        while self.current_index < len(self.api_keys):
            started = time.perf_counter()
            try:
                text = self._generate_once(
                    self.api_keys[self.current_index],
                    system_prompt,
                    user_prompt,
                    temperature,
                    max_output_tokens,
                )
                if not text:
                    raise RuntimeError("模型回覆為空。")
                latency = int((time.perf_counter() - started) * 1000)
                return GenerationResult(text=text, key_index=self.current_index, latency_ms=latency)
            except Exception as error:
                last_error = error
                recoverable = (
                    is_invalid_key_error(error)
                    or is_quota_error(error)
                    or is_transient_service_error(error)
                )
                if recoverable and self.current_index + 1 < len(self.api_keys):
                    self.current_index += 1
                    continue
                if is_invalid_key_error(error):
                    raise RuntimeError("Gemini API Key 無效，請回到設定頁重新確認。") from error
                if is_quota_error(error):
                    self.blocked_until = time.time() + self.cooldown_seconds
                    raise RuntimeError("所有 API Key 暫時達到額度或流量限制，請稍後再試。") from error
                if is_transient_service_error(error):
                    temporary_cooldown = min(self.cooldown_seconds, 30)
                    self.blocked_until = time.time() + temporary_cooldown
                    raise RuntimeError(
                        "Gemini 模型目前使用量較高，服務暫時忙碌；"
                        f"這不是 API Key 錯誤，請約 {temporary_cooldown} 秒後再試。"
                    ) from error
                raise RuntimeError(f"Gemini 生成失敗：{error}") from error
        self.blocked_until = time.time() + self.cooldown_seconds
        raise RuntimeError(f"Gemini 生成失敗：{last_error}")

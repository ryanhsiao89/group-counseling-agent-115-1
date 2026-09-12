"""Google GenAI SDK 包裝、金鑰輪替與錯誤分類。"""

from __future__ import annotations

import time
from dataclasses import dataclass


ENGINE_VERSION = "resilience-v1.6"


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
    model_name: str
    latency_ms: int


class GeminiKeyPool:
    def __init__(
        self,
        api_keys: list[str],
        model_name: str,
        cooldown_seconds: int = 90,
        fallback_model_names: tuple[str, ...] | list[str] = (
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
        ),
    ):
        if not api_keys:
            raise ValueError("至少需要一把 Gemini API Key。")
        self.api_keys = api_keys
        self.model_names = list(dict.fromkeys([model_name, *fallback_model_names]))
        self.model_name = self.model_names[0]
        self.cooldown_seconds = cooldown_seconds
        self.current_index = 0
        self.current_model_index = 0
        self.blocked_until = 0.0

    def _generate_once(
        self,
        api_key: str,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_output_tokens: int,
    ) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        def _finish_reason(response) -> str:
            try:
                candidates = getattr(response, "candidates", None) or []
                if not candidates:
                    return ""
                reason = getattr(candidates[0], "finish_reason", "")
                return str(reason or "").upper()
            except Exception:
                return ""

        def _generate_with_limit(token_limit: int):
            config_kwargs = {
                "system_instruction": system_prompt,
                "temperature": temperature,
                "max_output_tokens": token_limit,
            }

            # Gemini 3.x 預設會使用 thinking；團體角色回應不需要高推理量。
            # 使用 low 可降低 thought tokens 佔滿輸出上限、導致句子被截斷的風險。
            if model_name.startswith("gemini-3"):
                config_kwargs["thinking_config"] = types.ThinkingConfig(
                    thinking_level="low"
                )

            return client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )

        try:
            # 對話原本只給 600 tokens；Gemini thinking tokens 也計入上限，
            # 因此至少保留 1200，若仍碰到 MAX_TOKENS 再自動加大一次。
            first_limit = max(int(max_output_tokens), 1200)
            second_limit = max(first_limit * 2, 2000)

            response = _generate_with_limit(first_limit)
            text = str(getattr(response, "text", "") or "").strip()
            finish_reason = _finish_reason(response)

            if "MAX_TOKENS" in finish_reason:
                response = _generate_with_limit(second_limit)
                text = str(getattr(response, "text", "") or "").strip()
                finish_reason = _finish_reason(response)

            if "MAX_TOKENS" in finish_reason:
                raise RuntimeError(
                    "模型輸出仍因 MAX_TOKENS 被截斷，系統未採用不完整句子。"
                )

            return text

        except AttributeError:
            # 舊 SDK 相容路徑
            generation_config = {
                "temperature": temperature,
                "max_output_tokens": max(int(max_output_tokens), 1200),
            }
            if model_name.startswith("gemini-3"):
                generation_config["thinking_level"] = "low"

            interaction = client.interactions.create(
                model=model_name,
                input=user_prompt,
                system_instruction=system_prompt,
                generation_config=generation_config,
            )
            return str(getattr(interaction, "output_text", "") or "").strip()
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

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
        saw_quota_error = False
        saw_transient_error = False
        invalid_key_indexes: set[int] = set()

        current_pair = (self.current_index, self.current_model_index)
        candidate_pairs = [current_pair]
        candidate_pairs.extend(
            (key_index, model_index)
            for key_index in range(len(self.api_keys))
            for model_index in range(len(self.model_names))
            if (key_index, model_index) != current_pair
        )

        for key_index, model_index in candidate_pairs:
            if key_index in invalid_key_indexes:
                continue
            candidate_model = self.model_names[model_index]
            started = time.perf_counter()
            try:
                text = self._generate_once(
                    self.api_keys[key_index],
                    candidate_model,
                    system_prompt,
                    user_prompt,
                    temperature,
                    max_output_tokens,
                )
                if not text:
                    raise RuntimeError("模型回覆為空。")
                latency = int((time.perf_counter() - started) * 1000)
                self.current_index = key_index
                self.current_model_index = model_index
                self.model_name = candidate_model
                return GenerationResult(
                    text=text,
                    key_index=key_index,
                    model_name=candidate_model,
                    latency_ms=latency,
                )
            except Exception as error:
                last_error = error
                if is_invalid_key_error(error):
                    invalid_key_indexes.add(key_index)
                    continue
                if is_quota_error(error):
                    saw_quota_error = True
                    continue
                if is_transient_service_error(error):
                    saw_transient_error = True
                    continue
                raise RuntimeError(f"Gemini 生成失敗：{error}") from error

        if invalid_key_indexes and len(invalid_key_indexes) == len(self.api_keys):
            raise RuntimeError("所有 Gemini API Key 都無效，請回到設定頁重新確認。") from last_error
        if saw_transient_error:
            temporary_cooldown = min(self.cooldown_seconds, 30)
            self.blocked_until = time.time() + temporary_cooldown
            raise RuntimeError(
                "Gemini 所有備援模型目前都暫時忙碌；"
                f"這不是 API Key 錯誤，請約 {temporary_cooldown} 秒後再試。"
            ) from last_error
        if saw_quota_error:
            self.blocked_until = time.time() + self.cooldown_seconds
            raise RuntimeError("所有 API Key 與備援模型暫時達到額度或流量限制，請稍後再試。") from last_error
        self.blocked_until = time.time() + self.cooldown_seconds
        raise RuntimeError(f"Gemini 生成失敗：{last_error}")

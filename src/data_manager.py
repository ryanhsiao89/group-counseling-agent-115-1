"""Google Sheets 資料層。

採 append-only 設計：開始、結束、摘要與重新評量皆新增紀錄，不覆寫原始資料。
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from typing import Any, Mapping

from .models import next_stage
from .utils import json_dumps, json_loads, new_id, now_iso


SHEET_HEADERS: dict[str, list[str]] = {
    "Sessions": [
        "event_id", "event_type", "participant_id", "session_id", "group_series_id",
        "agent_type", "role_mode", "group_type", "stage", "school_id", "school_name",
        "started_at", "ended_at", "duration_seconds", "model_name", "prompt_version",
        "temperature", "completion_status", "participants_json", "base_context", "error_message",
    ],
    "ChatLogs": [
        "turn_id", "session_id", "group_series_id", "participant_id", "turn_index",
        "speaker_role", "speaker_id", "speaker_name", "content_raw", "timestamp",
        "stage_at_turn", "school_id", "role_mode", "message_type", "source",
        "latency_ms", "error_flag",
    ],
    "StageSummaries": [
        "summary_id", "session_id", "group_series_id", "participant_id", "stage",
        "group_theme", "emotional_tone", "relationship_state", "unfinished_issues_json",
        "leader_interventions_json", "member_states_json", "carryover_summary",
        "raw_model_output", "parsed_json", "model_name", "prompt_version", "created_at",
    ],
    "Assessments": [
        "assessment_id", "session_id", "group_series_id", "participant_id", "role_mode",
        "stage", "school_id", "rubric_version", "dimension_scores_json", "strengths_json",
        "improvement_points_json", "quoted_examples_json", "stage_fit", "approach_fit",
        "next_practice_task", "raw_model_output", "parsed_json", "model_name", "created_at",
    ],
    "SeriesStates": [
        "state_id", "group_series_id", "participant_id", "active", "updated_at",
        "last_completed_stage", "next_stage", "role_mode", "group_type", "school_id",
        "school_name", "base_context", "participants_json", "member_states_json",
        "prior_summary_json", "carryover_context",
    ],
}


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json_dumps(value)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return value


def summarize_completed_usage(
    rows: list[dict[str, Any]], participant_id: str
) -> dict[str, int]:
    """統計學生已完成練習的有效累積秒數，並避免重複計入同一 Session。"""
    completed_sessions: dict[str, tuple[int, str]] = {}
    for row in rows:
        if str(row.get("participant_id", "")) != participant_id:
            continue
        if str(row.get("event_type", "")).strip().lower() != "end":
            continue
        if str(row.get("completion_status", "")).strip().lower() != "completed":
            continue

        session_id = str(row.get("session_id", "")).strip()
        if not session_id:
            continue
        try:
            duration_seconds = max(0, int(float(row.get("duration_seconds", 0) or 0)))
        except (TypeError, ValueError):
            duration_seconds = 0
        role_mode = str(row.get("role_mode", "")).strip().lower()

        previous = completed_sessions.get(session_id)
        if previous is None or duration_seconds > previous[0]:
            completed_sessions[session_id] = (duration_seconds, role_mode)

    total_seconds = sum(item[0] for item in completed_sessions.values())
    leader_seconds = sum(
        duration for duration, role_mode in completed_sessions.values() if role_mode == "leader"
    )
    member_seconds = sum(
        duration for duration, role_mode in completed_sessions.values() if role_mode == "member"
    )
    return {
        "total_seconds": total_seconds,
        "leader_seconds": leader_seconds,
        "member_seconds": member_seconds,
        "completed_sessions": len(completed_sessions),
    }


class BaseStore:
    persistent = False

    def append(self, sheet_name: str, record: Mapping[str, Any]) -> None:
        raise NotImplementedError

    def records(self, sheet_name: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def append_session_event(self, record: Mapping[str, Any]) -> None:
        payload = {"event_id": new_id("evt"), **record}
        self.append("Sessions", payload)

    def append_turn(self, record: Mapping[str, Any]) -> None:
        payload = {"turn_id": new_id("turn"), **record}
        self.append("ChatLogs", payload)

    def append_stage_summary(self, record: Mapping[str, Any]) -> None:
        payload = {"summary_id": new_id("sum"), **record}
        self.append("StageSummaries", payload)

    def append_assessment(self, record: Mapping[str, Any]) -> None:
        payload = {"assessment_id": new_id("assess"), **record}
        self.append("Assessments", payload)

    def append_series_state(self, record: Mapping[str, Any]) -> None:
        payload = {"state_id": new_id("state"), **record}
        self.append("SeriesStates", payload)

    def usage_summary_for(self, participant_id: str) -> dict[str, int]:
        return summarize_completed_usage(self.records("Sessions"), participant_id)

    def continuations_for(self, participant_id: str) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self.records("SeriesStates"):
            if row.get("participant_id") != participant_id:
                continue
            series_id = str(row.get("group_series_id", ""))
            if not series_id:
                continue
            if series_id not in latest or str(row.get("updated_at", "")) > str(latest[series_id].get("updated_at", "")):
                latest[series_id] = row

        results = []
        for row in latest.values():
            active = str(row.get("active", "")).upper() in {"TRUE", "1", "YES"}
            if not active:
                continue
            parsed = dict(row)
            parsed["participants"] = json_loads(str(row.get("participants_json", "")), [])
            parsed["member_states"] = json_loads(str(row.get("member_states_json", "")), {})
            parsed["prior_summary"] = json_loads(str(row.get("prior_summary_json", "")), {})
            results.append(parsed)
        return sorted(results, key=lambda x: str(x.get("updated_at", "")), reverse=True)

    def table_rows(self, sheet_name: str) -> list[dict[str, Any]]:
        if sheet_name not in SHEET_HEADERS:
            raise KeyError(sheet_name)
        return self.records(sheet_name)


class InMemoryStore(BaseStore):
    """未設定雲端時的單一執行程序暫存，也供測試使用。"""

    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = threading.Lock()

    def append(self, sheet_name: str, record: Mapping[str, Any]) -> None:
        if sheet_name not in SHEET_HEADERS:
            raise KeyError(sheet_name)
        row = {header: _cell(record.get(header, "")) for header in SHEET_HEADERS[sheet_name]}
        with self._lock:
            self._tables[sheet_name].append(row)

    def records(self, sheet_name: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._tables.get(sheet_name, [])]


class GoogleSheetsStore(BaseStore):
    persistent = True

    def __init__(self, spreadsheet_id: str, service_account: Mapping[str, Any]) -> None:
        import gspread

        credentials = dict(service_account)
        if "private_key" in credentials:
            credentials["private_key"] = str(credentials["private_key"]).replace("\\n", "\n")
        client = gspread.service_account_from_dict(credentials)
        self.book = client.open_by_key(spreadsheet_id)
        self._worksheets: dict[str, Any] = {}
        self._headers: dict[str, list[str]] = {}
        self._lock = threading.Lock()
        self.ensure_schema()

    def ensure_schema(self) -> None:
        existing = {worksheet.title: worksheet for worksheet in self.book.worksheets()}
        for name, headers in SHEET_HEADERS.items():
            worksheet = existing.get(name)
            if worksheet is None:
                worksheet = self.book.add_worksheet(title=name, rows=1000, cols=max(20, len(headers)))
                worksheet.append_row(headers, value_input_option="RAW")
                actual_headers = list(headers)
            else:
                first_row = worksheet.row_values(1)
                if not first_row:
                    worksheet.append_row(headers, value_input_option="RAW")
                    actual_headers = list(headers)
                elif first_row != headers:
                    missing = [header for header in headers if header not in first_row]
                    if missing:
                        first_row = first_row + missing
                        worksheet.update(values=[first_row], range_name="A1")
                    actual_headers = list(first_row)
                else:
                    actual_headers = list(headers)
            self._worksheets[name] = worksheet
            self._headers[name] = actual_headers

    def append(self, sheet_name: str, record: Mapping[str, Any]) -> None:
        headers = self._headers[sheet_name]
        values = [_cell(record.get(header, "")) for header in headers]
        with self._lock:
            self._worksheets[sheet_name].append_row(values, value_input_option="RAW")

    def records(self, sheet_name: str) -> list[dict[str, Any]]:
        with self._lock:
            return self._worksheets[sheet_name].get_all_records(default_blank="")


def create_store(secrets: Mapping[str, Any] | None) -> BaseStore:
    """依 Secrets 建立資料層，並相容新舊兩種服務帳戶格式。

    支援：
    1. 新版 TOML 表格：``[gcp_service_account]``
    2. 舊版整份 JSON：``GOOGLE_SERVICE_ACCOUNT_JSON = '''{...}'''``
    """
    if secrets is None:
        return InMemoryStore()

    settings = dict(secrets.get("google_sheets", {}))
    spreadsheet_id = str(
        settings.get("spreadsheet_id", "")
        or secrets.get("GOOGLE_SPREADSHEET_ID", "")
        or secrets.get("GOOGLE_SHEET_ID", "")
    ).strip()

    service_account = dict(secrets.get("gcp_service_account", {}))
    # 除了正式的最外層設定，也容許使用者誤把舊版 JSON 放在
    # [google_sheets] 之下；Streamlit/TOML 初次設定時很容易發生這種情況。
    legacy_json = (
        secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        or settings.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        or settings.get("service_account_json", "")
    )
    if not service_account and legacy_json:
        if isinstance(legacy_json, str):
            try:
                parsed = json.loads(legacy_json)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "GOOGLE_SERVICE_ACCOUNT_JSON 不是有效的 JSON；請完整複製舊 Agent 的三引號內容。"
                ) from exc
            if not isinstance(parsed, dict):
                raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON 必須是一個 JSON 物件。")
            service_account = parsed
        else:
            service_account = dict(legacy_json)

    # 亦支援直接把服務帳戶欄位寫在 [google_sheets] 內。只擷取 Google
    # 憑證欄位，避免把 spreadsheet_id 一併傳給 google-auth。
    if not service_account:
        credential_keys = {
            "type",
            "project_id",
            "private_key_id",
            "private_key",
            "client_email",
            "client_id",
            "auth_uri",
            "token_uri",
            "auth_provider_x509_cert_url",
            "client_x509_cert_url",
            "universe_domain",
        }
        nested_credentials = {
            key: settings[key]
            for key in credential_keys
            if key in settings and str(settings[key]).strip()
        }
        if nested_credentials:
            service_account = nested_credentials

    # 完全沒有設定時保留測試用記憶體模式；只要使用者已設定其中一部分，
    # 就回報可操作且不洩漏憑證內容的明確錯誤。
    if not spreadsheet_id and not service_account:
        if not secrets:
            return InMemoryStore()
        raise ValueError(
            "Secrets 未讀到 Google Sheets 設定：請確認 [google_sheets] 的 "
            "spreadsheet_id，以及最外層 GOOGLE_SERVICE_ACCOUNT_JSON。"
        )
    if not spreadsheet_id:
        raise ValueError("Secrets 已讀到服務帳戶，但缺少 [google_sheets] spreadsheet_id。")
    if not service_account:
        raise ValueError(
            "Secrets 已讀到 spreadsheet_id，但未讀到服務帳戶；請把 "
            "GOOGLE_SERVICE_ACCOUNT_JSON 放在任何 [區段] 之前。"
        )

    required_keys = ("type", "project_id", "private_key", "client_email", "token_uri")
    missing_keys = [key for key in required_keys if not str(service_account.get(key, "")).strip()]
    if missing_keys:
        raise ValueError(
            "Google 服務帳戶資料不完整，缺少欄位：" + ", ".join(missing_keys)
        )

    return GoogleSheetsStore(spreadsheet_id, service_account)


def make_series_state(
    *,
    group_series_id: str,
    participant_id: str,
    completed_stage: str,
    role_mode: str,
    group_type: str,
    school_id: str,
    school_name: str,
    base_context: str,
    participants: list[dict[str, Any]],
    member_states: dict[str, Any],
    prior_summary: dict[str, Any],
    carryover_context: str,
) -> dict[str, Any]:
    upcoming = next_stage(completed_stage)
    return {
        "group_series_id": group_series_id,
        "participant_id": participant_id,
        "active": bool(upcoming),
        "updated_at": now_iso(),
        "last_completed_stage": completed_stage,
        "next_stage": upcoming or "",
        "role_mode": role_mode,
        "group_type": group_type,
        "school_id": school_id,
        "school_name": school_name,
        "base_context": base_context,
        "participants_json": participants,
        "member_states_json": member_states,
        "prior_summary_json": prior_summary,
        "carryover_context": carryover_context,
    }

"""依本機 .streamlit/secrets.toml 建立或核對 Google Sheets 工作表。"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data_manager import GoogleSheetsStore, SHEET_HEADERS  # noqa: E402


def main() -> int:
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        print("找不到 .streamlit/secrets.toml；請先由 secrets.toml.example 複製並填入設定。")
        return 1
    with secrets_path.open("rb") as handle:
        secrets = tomllib.load(handle)
    spreadsheet_id = str(secrets.get("google_sheets", {}).get("spreadsheet_id", ""))
    service_account = secrets.get("gcp_service_account", {})
    if not spreadsheet_id or not service_account:
        print("缺少 google_sheets.spreadsheet_id 或 gcp_service_account。")
        return 1
    GoogleSheetsStore(spreadsheet_id, service_account)
    print("Google Sheets 結構已就緒：" + "、".join(SHEET_HEADERS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

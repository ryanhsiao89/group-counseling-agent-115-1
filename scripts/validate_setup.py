"""部署前快速檢查本機設定，不顯示任何密碼內容。"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PACKAGES = ("streamlit", "google.genai", "gspread", "pandas")


def main() -> int:
    errors: list[str] = []
    for package in REQUIRED_PACKAGES:
        if importlib.util.find_spec(package) is None:
            errors.append(f"尚未安裝套件：{package}")

    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        errors.append("找不到 .streamlit/secrets.toml")
    else:
        with secrets_path.open("rb") as handle:
            data = tomllib.load(handle)
        checks = {
            "app.participant_salt": data.get("app", {}).get("participant_salt"),
            "app.teacher_test_emails": data.get("app", {}).get("teacher_test_emails"),
            "email.sender_email": data.get("email", {}).get("sender_email"),
            "email.app_password": data.get("email", {}).get("app_password"),
            "google_sheets.spreadsheet_id": data.get("google_sheets", {}).get("spreadsheet_id"),
            "gcp_service_account.client_email": data.get("gcp_service_account", {}).get("client_email"),
            "gcp_service_account.private_key": data.get("gcp_service_account", {}).get("private_key"),
        }
        for name, value in checks.items():
            if not value:
                errors.append(f"缺少設定：{name}")

    if errors:
        print("部署前檢查未通過：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("部署前檢查通過。可執行：streamlit run app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""教學系統的基本安全攔截；不是臨床風險評估器。"""

from __future__ import annotations

import re


IMMEDIATE_RISK_PATTERNS = (
    r"我(現在|今天|今晚)?\s*(想|要|準備|決定)\s*(自殺|去死|結束生命)",
    r"我(現在|今天|今晚)?\s*(想|要|準備|決定)\s*(傷害|殺)\s*(自己|別人|他|她)",
    r"(已經|正在)\s*(割腕|吞藥|上吊|準備跳下去)",
    r"有(自殺|傷人)計畫",
)


def detect_immediate_risk(text: str) -> bool:
    normalized = text.replace(" ", "")
    return any(re.search(pattern, normalized) for pattern in IMMEDIATE_RISK_PATTERNS)


def crisis_message() -> str:
    return (
        "這個系統只能用於教學模擬，不能處理真實的緊急危機。"
        "如果這是你本人或身邊的人現在正面臨的情況，請立刻聯絡可信任的真人並前往安全處所；"
        "有立即危險請撥 119 或 110，也可撥衛生福利部 1925 安心專線、生命線 1995 或張老師 1980。"
    )

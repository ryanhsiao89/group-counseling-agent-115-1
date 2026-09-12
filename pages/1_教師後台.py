"""教師端唯讀查詢與匯出頁面。"""

from __future__ import annotations

import csv
import hmac
import io
import zipfile

import pandas as pd
import streamlit as st

from src.data_manager import InMemoryStore, SHEET_HEADERS, create_store


st.set_page_config(page_title="團體諮商 Agent 教師後台", page_icon="📊", layout="wide")


def section(name: str) -> dict:
    try:
        return dict(st.secrets.get(name, {}))
    except Exception:
        return {}


@st.cache_resource
def get_admin_store():
    try:
        return create_store(st.secrets), ""
    except Exception as error:
        return InMemoryStore(), str(error)


def csv_bytes(rows: list[dict], headers: list[str]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def all_tables_zip(store) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, headers in SHEET_HEADERS.items():
            archive.writestr(f"{name}.csv", csv_bytes(store.table_rows(name), headers))
    return output.getvalue()


app_settings = section("app")
admin_passcode = str(app_settings.get("admin_passcode", ""))
if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

st.title("📊 團體諮商 Agent 教師後台")
if not admin_passcode:
    st.error("尚未在 Streamlit Secrets 設定 app.admin_passcode，教師後台已鎖定。")
    st.stop()

if not st.session_state.admin_authenticated:
    entered = st.text_input("教師後台密碼", type="password")
    if st.button("登入教師後台", type="primary"):
        if hmac.compare_digest(entered, admin_passcode):
            st.session_state.admin_authenticated = True
            st.rerun()
        st.error("密碼不正確。")
    st.stop()

store, error = get_admin_store()
if not store.persistent:
    st.warning(f"Google Sheets 尚未連線，現在只有此執行程序的暫存資料。{error}")

sessions = store.table_rows("Sessions")
chat_logs = store.table_rows("ChatLogs")
assessments = store.table_rows("Assessments")
completed = [row for row in sessions if row.get("event_type") == "end" and row.get("completion_status") == "completed"]

col1, col2, col3, col4 = st.columns(4)
col1.metric("匿名學生數", len({row.get("participant_id") for row in sessions if row.get("participant_id")}))
col2.metric("完成階段數", len(completed))
col3.metric("逐輪紀錄數", len(chat_logs))
col4.metric("形成性回饋數", len(assessments))

participant_filter = st.text_input("篩選匿名 participant_id（可留白）").strip()
table_name = st.selectbox("查看資料表", list(SHEET_HEADERS))
rows = store.table_rows(table_name)
if participant_filter:
    rows = [row for row in rows if participant_filter.lower() in str(row.get("participant_id", "")).lower()]

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
st.download_button(
    f"下載 {table_name}.csv",
    data=csv_bytes(rows, SHEET_HEADERS[table_name]),
    file_name=f"{table_name}.csv",
    mime="text/csv",
)
st.download_button(
    "下載全部資料表 ZIP",
    data=all_tables_zip(store),
    file_name="GroupCounselingAgent_Exports.zip",
    mime="application/zip",
)

if st.button("登出教師後台"):
    st.session_state.admin_authenticated = False
    st.rerun()

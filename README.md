# 115-1 團體諮商 AI Agent

這是一套可部署於 Streamlit Community Cloud 的繁體中文團體諮商教學模擬系統。學生可選擇擔任 Leader 或 Member，依開始期、形成期、工作期、結束期進行同一團體的連續練習，並選擇 11 種諮商學派或整合取向。

## 已完成的核心功能

- `@hcu.edu.tw` 學校 Email OTP 驗證。
- 教師測試信箱白名單；範例已放入 `ryanhsiao89@gmail.com`。
- 學生使用自己的 Gemini API Key；Key 只存在目前 Streamlit Session，不寫入任何資料表。
- Leader 模式：學生帶領 3 名固定 AI 成員。
- Member 模式：AI Leader 示範所選學派，學生與 2 名固定 AI 成員共同參與。
- Opening、Formation、Working、Ending 四階段；可一次接續，也可跨日讀取前次摘要續談。
- 同一團體系列固定成員、persona、member state、主題、角色與學派。
- 工作期提高成員對成員的橫向互動；結束期處理收穫、離別與未竟感受。
- 每次練習可下載 UTF-8 BOM 逐字稿。
- Google Sheets 自動建立並完整記錄 Sessions、ChatLogs、StageSummaries、Assessments、SeriesStates。
- AI 原始輸出與解析 JSON 分開保存；重新分析不需覆寫原資料。
- 教師後台可檢視與下載單表 CSV 或全表 ZIP。
- 明確即時自傷／他傷訊息的安全攔截與台灣真人求助方向。

## 專案結構

```text
group-counseling-agent-115-1/
├── app.py                         # 學生端主程式
├── pages/1_教師後台.py            # 教師唯讀後台與資料匯出
├── src/
│   ├── auth.py                    # Email、OTP、匿名代碼
│   ├── config.py                  # 設定
│   ├── data_manager.py            # Google Sheets append-only 資料層
│   ├── llm_client.py              # Gemini SDK 與多 Key 輪替
│   ├── models.py                  # 四階段與資料物件
│   ├── personas.py                # 成員角色庫
│   ├── prompts.py                 # 學派、階段、摘要與評量提示詞
│   ├── safety.py                  # 基本安全攔截
│   ├── session_service.py         # 新團體、續談、發言與逐字稿
│   └── utils.py
├── scripts/
│   ├── init_google_sheets.py      # 建立／核對工作表
│   └── validate_setup.py          # 部署前設定檢查
├── tests/                         # 不呼叫 Gemini 的單元測試
├── docs/                          # 部署、學生手冊、欄位與驗收文件
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── requirements.txt
└── runtime.txt
```

## 本機快速啟動

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
```

填好 `.streamlit/secrets.toml` 後：

```powershell
python scripts\validate_setup.py
python scripts\init_google_sheets.py
pytest
streamlit run app.py
```

完整設定請看 [部署與設定說明](docs/部署與設定說明.md)。

## 安全原則

- 不要把 `.streamlit/secrets.toml`、服務帳戶 JSON、Gmail App Password 或學生 API Key 上傳到 GitHub。
- Google Sheets 只保存 HMAC 產生的匿名 `participant_id`，不保存登入 Email 或 OTP。
- 本系統是教學模擬，不是心理治療、診斷、危機評估或正式能力測驗。
- AI 分數僅供形成性回饋與教師參考；正式評分前仍需專家驗證。

## 技術依據

- Google 建議使用正式的 `google-genai` SDK：[Gemini API libraries](https://ai.google.dev/gemini-api/docs/libraries)
- Gemini API Key 申請與安全：[Using Gemini API keys](https://ai.google.dev/gemini-api/docs/api-key)
- Streamlit Secrets：[Secrets management](https://docs.streamlit.io/develop/concepts/connections/secrets-management)
- Google Cloud 服務帳戶：[Service accounts overview](https://cloud.google.com/iam/docs/service-account-overview)
- 台灣心理健康與救援專線：[衛生福利部全國諮詢及救援服務專線](https://dep.mohw.gov.tw/DOMHAOH/fp-327-8715-107.html)

# Google Sheets 資料表與欄位說明

本系統採 append-only 記錄方式。Session 開始與結束各新增一列；摘要與評量也各自保存原始模型輸出及解析結果，不覆寫既有研究資料。

## Sessions

每一階段是一個獨立 `session_id`，四階段共用同一個 `group_series_id`。

主要欄位包括匿名 `participant_id`、角色、團體主題、階段、學派、開始／結束時間、實際秒數、模型、提示詞版本、完成狀態、成員清單與前情提要。`event_type` 可為 `start` 或 `end`。

## ChatLogs

保存每一輪原始文字及順序，包括：

- `speaker_role`：student_leader、student_member、ai_leader、ai_group_member 或 system。
- `speaker_id` 與 `speaker_name`。
- `content_raw`：原始內容，不覆寫。
- `stage_at_turn`、`school_id`、`role_mode`。
- `latency_ms` 與 `error_flag`。

## StageSummaries

每次結束階段後保存：

- 團體核心主題與情緒氣氛。
- 成員關係狀態。
- 未完成議題。
- 帶領者主要介入。
- 每位成員的 safety_trust、emotion、engagement、conflict、unfinished_issue。
- 下一階段 carryover summary。
- `raw_model_output` 與 `parsed_json`。

## Assessments

Leader 模式使用六向度團體帶領回饋；Member 模式則使用參與與體驗回饋，不會拿帶領者規準評量學生。

保存向度分數、具體優點、改善點、逐字稿引用、替代回應、階段適配、學派契合與下一次任務。AI 分數只供形成性學習，不是標準化成績。

## SeriesStates

這張表支援跨日續談。每完成一階段便新增一筆最新狀態，包含固定成員、member state、前階段摘要、最近逐字稿節錄與下一階段。完成 Ending 後 `active` 會變成 FALSE，不再列為可續談團體。

## 隱私界線

- Email 只用來寄 OTP 與在記憶體中產生 HMAC 匿名代碼，不寫入五張研究資料表。
- OTP 與學生 Gemini API Key 不寫入 Google Sheets。
- `participant_salt` 必須保持私密且固定，否則匿名代碼無法穩定連結。

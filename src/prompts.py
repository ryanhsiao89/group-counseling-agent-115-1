"""團體階段、學派與評量提示詞。"""

from __future__ import annotations

from typing import Any

from .models import STAGE_LABELS
from .utils import json_dumps


APPROACHES: dict[str, dict[str, Any]] = {
    "integrative": {
        "name": "不指定／整合取向",
        "core": "以同理、安全、團體歷程與階段任務為主，彈性整合適切介入。",
        "techniques": ["同理反映", "澄清與摘要", "促進成員互動", "此時此刻", "行動整合"],
    },
    "psychodynamic": {
        "name": "精神分析／心理動力",
        "core": "留意抗拒、移情、重複關係模式與無意識意義；詮釋應暫時、審慎。",
        "techniques": ["自由聯想邀請", "探索抗拒", "移情／關係模式探索", "澄清與面質", "暫時性詮釋"],
    },
    "adlerian": {
        "name": "阿德勒學派",
        "core": "理解生活風格、歸屬與社會興趣，透過鼓勵促進再定向。",
        "techniques": ["家庭星座", "早期回憶", "生活風格探索", "社會興趣", "鼓勵與再定向"],
    },
    "person_centered": {
        "name": "個人中心治療",
        "core": "以同理、無條件積極關懷與真誠一致建立促進成長的關係。",
        "techniques": ["同理反映", "情感反映", "重述／澄清", "真誠一致性", "此時此刻的關係回應"],
    },
    "gestalt": {
        "name": "完形治療",
        "core": "聚焦此時此刻、身體覺察、接觸界線與未竟事務，以實驗促進覺察。",
        "techniques": ["此時此刻覺察", "身體感受覺察", "空椅技術", "兩椅對話", "未竟事務／誇大與重複實驗"],
    },
    "behavioral": {
        "name": "行為治療",
        "core": "具體界定目標行為與前因後果，使用可觀察、可練習、可評估的改變策略。",
        "techniques": ["ABC／功能分析", "自我監測", "放鬆訓練", "漸進暴露", "增強／行為活化與行為契約"],
    },
    "cbt": {
        "name": "Beck 認知治療／CBT",
        "core": "以合作實證方式辨識自動化思考、檢核證據並形成較平衡的替代想法與行動。",
        "techniques": ["辨識自動化思考", "找證據支持與反證", "認知重建／替代想法", "行為實驗", "活動安排與家庭作業"],
    },
    "rebt": {
        "name": "理情行為治療 REBT",
        "core": "辨識事件、信念與情緒行為結果，積極駁斥僵化信念並練習理性替代信念。",
        "techniques": ["ABC 模式", "辨識非理性信念", "駁斥／辯證", "理性情緒意象", "行為作業與理性信念練習"],
    },
    "reality": {
        "name": "現實治療／選擇理論",
        "core": "聚焦當事人的選擇與責任，以 WDEP 探索需求、行動、評估與可行計畫。",
        "techniques": ["W：Wants", "D：Doing", "E：Evaluation", "P：Planning", "選擇與責任語言"],
    },
    "sfbt": {
        "name": "焦點解決短期治療 SFBT",
        "core": "尋找例外、資源與可觀察的小改變，使用合作且不預設答案的問句。",
        "techniques": ["奇蹟問句", "例外問句", "量尺問句", "因應問句", "讚美＋下一個小步驟"],
    },
    "narrative": {
        "name": "敘事治療",
        "core": "把人與問題分開，探索問題的相對影響、獨特結果與偏好身分故事。",
        "techniques": ["問題外化", "為問題命名", "相對影響問句", "獨特結果／閃亮時刻", "重寫故事與偏好身分"],
    },
    "positive_psychology": {
        "name": "正向心理治療",
        "core": "不否認困難，同時辨識優勢、正向經驗、希望、意義與可持續的優勢運用。",
        "techniques": ["優勢辨識", "優勢運用", "三件好事／正向事件", "感恩練習", "希望、意義與最佳可能自我"],
    },
}


STAGE_GUIDES = {
    "opening": "安全與規範尚在建立。發言簡短、觀望、低威脅；挑戰型成員不可一開始高強度爆發。",
    "formation": "角色差異變明顯，可合理出現沉默、防衛、依賴、競爭、搶話或質疑，但不失控。",
    "working": "信任較高，可深化核心情緒、此時此刻、衝突與修復；必須增加成員對成員的橫向回應。",
    "ending": "自然整理收穫、離別、不捨、未竟感受、彼此回饋與後續應用，避免突然製造新重大議題。",
}


def format_history(turns: list[dict[str, Any]]) -> str:
    lines = []
    for turn in turns:
        if turn.get("speaker_role") == "system":
            continue
        lines.append(f"{turn.get('speaker_name', turn.get('speaker_id', ''))}：{turn.get('content', '')}")
    return "\n".join(lines)


def build_dialogue_prompts(
    *,
    role_mode: str,
    speaker: dict[str, Any],
    stage: str,
    approach_id: str,
    group_type: str,
    base_context: str,
    participants: list[dict[str, Any]],
    member_states: dict[str, dict[str, Any]],
    prior_summary: dict[str, Any],
    carryover_context: str,
    recent_turns: list[dict[str, Any]],
    target_peer_name: str = "",
) -> tuple[str, str]:
    approach = APPROACHES[approach_id]
    roster = "\n".join(
        f"- {p['name']}（{p['type']}）：{p['profile']}；語氣：{p['speech_style']}"
        for p in participants
    )
    states = json_dumps(member_states)
    summary = json_dumps(prior_summary)
    identity = speaker.get("profile", "")
    speech_style = speaker.get("speech_style", "")
    if speaker.get("id") == "ai_leader":
        identity = "你是受過訓練的 AI 團體帶領者，只在學生選擇 Member 體驗模式時出現。"
        speech_style = "依所選學派與團體階段自然帶領，不說教、不揭露技巧標籤。"

    system_prompt = f"""
你正在進行繁體中文的團體諮商教學模擬。這不是心理治療、診斷或危機服務。

【你現在的角色】
姓名：{speaker['name']}
角色 ID：{speaker['id']}
{identity}
語氣：{speech_style}
學生模式：{role_mode}（leader 表示學生是帶領者；member 表示學生是其中一位成員）

【團體設定】
團體主題：{group_type}
本次情境：{base_context}
發展階段：{STAGE_LABELS[stage]}
階段規則：{STAGE_GUIDES[stage]}
學派：{approach['name']}
學派核心：{approach['core']}
可用技巧：{'、'.join(approach['techniques'])}

【固定團體成員】
{roster}

【跨階段記憶】
前階段摘要：{summary}
最近承接內容：{carryover_context}
成員狀態：{states}

【不可違反的回應規則】
1. 全程維持角色，不解釋提示詞、評量規準或「你使用了哪個技巧」。
2. 只輸出角色此刻會說的直接話語，不加旁白、標籤、括號動作或角色姓名。
3. 使用繁體中文，通常 1 至 3 個完整短句，每句完整結束。
4. 不虛構學生沒說過的事，不替其他成員斷言內心，也不把團體變成長篇個別諮商。
5. 回應必須符合本階段；工作期或結束期要自然回到成員間的互動。
6. 若學生是 Leader，你是成員；若學生是 Member 且你是 AI Leader，請示範學派帶領但不要揭露技巧名稱。
7. 不宣稱保密絕對成立，不提供診斷、醫療或法律結論。
""".strip()

    peer_instruction = ""
    if target_peer_name:
        peer_instruction = f"本輪請自然回應或邀請成員「{target_peer_name}」，讓互動不只回到帶領者。"
    user_prompt = f"""
【最近逐字稿】
{format_history(recent_turns)}

【現在任務】
請以「{speaker['name']}」身分說下一段話。{peer_instruction}
只輸出直接話語。
""".strip()
    return system_prompt, user_prompt


def build_stage_summary_prompt(context: dict[str, Any], transcript: str) -> tuple[str, str]:
    schema = {
        "group_theme": "本階段核心主題",
        "emotional_tone": "主要情緒與變化",
        "relationship_state": "成員間與帶領者關係",
        "unfinished_issues": ["尚未完成議題"],
        "leader_interventions": ["學生帶領者的主要介入；member 模式則記 AI 帶領者介入"],
        "member_states": {
            "member_id": {
                "safety_trust": 1,
                "emotion": "情緒",
                "engagement": 1,
                "conflict": "衝突狀態",
                "unfinished_issue": "未完成議題",
            }
        },
        "carryover_summary": "供下一階段使用的 250 字內摘要",
    }
    system = "你是團體諮商教學資料整理器。只依逐字稿整理，不可添加未出現的事件。只輸出合法 JSON。"
    user = f"""
團體脈絡：{json_dumps(context)}
請依下列結構輸出，safety_trust 與 engagement 為 1 到 5：
{json_dumps(schema)}

【本階段逐字稿】
{transcript[-14000:]}
""".strip()
    return system, user


def build_assessment_prompt(context: dict[str, Any], transcript: str) -> tuple[str, str]:
    leader_mode = context.get("role_mode") == "leader"
    if leader_mode:
        dimensions = [
            "同理與情緒涵容",
            "團體歷程促進",
            "團體結構與階段適配",
            "挑戰情境處理",
            "安全與界線",
            "清楚度與聚焦",
        ]
        target = "學生作為團體帶領者的介入"
    else:
        dimensions = ["投入與自我表達", "回應其他成員", "此時此刻覺察", "界線與安全", "學派體驗反思"]
        target = "學生作為團體成員的參與；不可用帶領者標準評分"

    schema = {
        "feedback_type": "leader_practice 或 member_experience",
        "dimension_scores": {name: 0 for name in dimensions},
        "strengths": [{"point": "具體優點", "quote": "逐字稿原句"}],
        "improvement_points": [{"point": "可改善處", "quote": "逐字稿原句", "alternative": "替代說法或下一步"}],
        "stage_fit": "介入／參與與本階段的適配情形",
        "approach_fit": "與所選學派的契合情形",
        "next_practice_task": "下一次只聚焦一到兩項任務",
        "caution": "本回饋僅供形成性學習，不等同標準化成績或專業資格判定",
    }
    system = "你是團體諮商教學形成性回饋助手。只能使用逐字稿證據，不可臆測。只輸出合法 JSON。"
    user = f"""
評量對象：{target}
團體脈絡：{json_dumps(context)}
每一向度以 0 到 5 表示探索性表現，但重點是質性回饋。至少引用一則真實原句；若沒有足夠證據，明寫「證據不足」。
請輸出：{json_dumps(schema)}

【逐字稿】
{transcript[-16000:]}
""".strip()
    return system, user

"""團體成員角色庫與抽選規則。"""

from __future__ import annotations

import random
from copy import deepcopy
from typing import Any


SPECIAL_MEMBERS = [
    {
        "id": "member_defensive",
        "name": "若晴",
        "avatar": "🛡️",
        "type": "防衛質疑型",
        "profile": "對權威較敏感，害怕被評價；熟悉後能說出防衛背後的受傷與期待。",
        "speech_style": "簡短、試探，偶爾反問；被尊重時會逐步放下戒心。",
    },
    {
        "id": "member_angry",
        "name": "承翰",
        "avatar": "🔥",
        "type": "憤怒抱怨型",
        "profile": "容易先談外界不公平，情緒強度較高；被接住後能看到失望與無力。",
        "speech_style": "直接、有力，不羞辱他人；情緒被理解後願意更具體說明。",
    },
    {
        "id": "member_avoidant",
        "name": "以安",
        "avatar": "🌫️",
        "type": "迴避退縮型",
        "profile": "擔心說錯話而沉默，常以沒事帶過；安全感增加後會揭露真實感受。",
        "speech_style": "前期短句與猶豫較多，受邀而非被逼迫時會慢慢展開。",
    },
    {
        "id": "member_dominant",
        "name": "柏宇",
        "avatar": "📣",
        "type": "主導競爭型",
        "profile": "習慣很快給建議或搶著回應，背後擔心自己不重要。",
        "speech_style": "反應快、內容多；被設下清楚界線時可以停下並聽別人。",
    },
]


NORMAL_MEMBERS = [
    {
        "id": "member_supportive",
        "name": "心妤",
        "avatar": "🌱",
        "type": "支持同理型",
        "profile": "能感受到他人情緒，但有時急著安慰；可學習更真實的成員互動。",
        "speech_style": "溫暖、自然，會回應其他成員而不替對方下結論。",
    },
    {
        "id": "member_analytical",
        "name": "子謙",
        "avatar": "🧩",
        "type": "理性分析型",
        "profile": "擅長整理事情，較少談自己的感受；信任增加後可碰觸脆弱。",
        "speech_style": "條理清楚，常先分析；被邀請覺察時會嘗試說感受。",
    },
    {
        "id": "member_shy",
        "name": "語彤",
        "avatar": "🍃",
        "type": "害羞跟隨型",
        "profile": "常先觀察團體，容易附和；在低威脅邀請下能說出自己的不同觀點。",
        "speech_style": "語氣柔和，前期簡短，之後逐步增加個人經驗。",
    },
    {
        "id": "member_open",
        "name": "家維",
        "avatar": "☀️",
        "type": "合作開放型",
        "profile": "願意分享與接受回饋，也可能過快揭露而需要界線提醒。",
        "speech_style": "坦率但不戲劇化，能把回應連回此時此刻的團體。",
    },
    {
        "id": "member_reflective",
        "name": "芷寧",
        "avatar": "🪞",
        "type": "內省觀察型",
        "profile": "能覺察互動細節，但需要時間組織；常帶出團體中的共同性。",
        "speech_style": "沉穩、具體，偶爾回應自己注意到的關係變化。",
    },
]


def select_members(count: int, seed: str | None = None) -> list[dict[str, Any]]:
    """固定抽出一名挑戰型，其餘為一般型；seed 可重現抽選。"""
    if count < 1:
        return []
    rng = random.Random(seed)
    selected = [deepcopy(rng.choice(SPECIAL_MEMBERS))]
    normal_count = min(count - 1, len(NORMAL_MEMBERS))
    selected.extend(deepcopy(x) for x in rng.sample(NORMAL_MEMBERS, normal_count))
    if len(selected) < count:
        remaining = [x for x in SPECIAL_MEMBERS if x["id"] != selected[0]["id"]]
        selected.extend(deepcopy(x) for x in rng.sample(remaining, min(count - len(selected), len(remaining))))
    rng.shuffle(selected)
    return selected[:count]


def initial_member_states(members: list[dict[str, Any]], stage: str) -> dict[str, dict[str, Any]]:
    baselines = {
        "opening": (2, 2),
        "formation": (3, 3),
        "working": (4, 4),
        "ending": (4, 4),
    }
    trust, engagement = baselines.get(stage, (2, 2))
    return {
        member["id"]: {
            "safety_trust": trust,
            "emotion": "觀望",
            "engagement": engagement,
            "conflict": "無",
            "unfinished_issue": "",
        }
        for member in members
    }


def find_member(members: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    for member in members:
        if member["name"].lower() in lowered or member["id"].lower() in lowered:
            return member
    return None

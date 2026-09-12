import random

from src.models import STAGES, next_stage
from src.personas import SPECIAL_MEMBERS, select_members
from src.prompts import APPROACHES, STAGE_GUIDES
from src.session_service import build_transcript, choose_speakers, create_new_context


def test_stage_order():
    assert STAGES == ("opening", "formation", "working", "ending")
    assert next_stage("opening") == "formation"
    assert next_stage("ending") is None


def test_member_selection_contains_challenge_member():
    members = select_members(3, seed="fixed")
    special_ids = {member["id"] for member in SPECIAL_MEMBERS}
    assert len(members) == 3
    assert sum(member["id"] in special_ids for member in members) == 1


def test_named_member_has_priority():
    context = create_new_context(
        participant_id="P_1",
        role_mode="leader",
        group_type="人際團體",
        stage="working",
        school_id="integrative",
        base_context="測試",
        duration_target_minutes=10,
    )
    named = context.participants[0]
    selected = choose_speakers(context, f"{named['name']}，你怎麼想？", [], random.Random(1))
    assert selected == [named]


def test_required_school_and_working_rules_exist():
    assert len(APPROACHES) == 12  # 11 學派加「不指定／整合」
    assert "成員對成員" in STAGE_GUIDES["working"]


def test_transcript_contains_role_stage_and_school():
    context = create_new_context(
        participant_id="P_1",
        role_mode="member",
        group_type="生涯團體",
        stage="formation",
        school_id="adlerian",
        base_context="測試",
        duration_target_minutes=0,
    )
    transcript = build_transcript(context, [])
    assert "Member 團體成員" in transcript
    assert "形成期 Formation" in transcript
    assert "阿德勒學派" in transcript

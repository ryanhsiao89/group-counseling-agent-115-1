from src.data_manager import InMemoryStore, make_series_state


def test_append_only_series_state_can_be_loaded_for_continuation():
    store = InMemoryStore()
    state = make_series_state(
        group_series_id="series_1",
        participant_id="P_1",
        completed_stage="opening",
        role_mode="leader",
        group_type="人際關係團體",
        school_id="gestalt",
        school_name="完形治療",
        base_context="測試情境",
        participants=[{"id": "m1", "name": "小明"}],
        member_states={"m1": {"safety_trust": 3}},
        prior_summary={"carryover_summary": "摘要"},
        carryover_context="最近對話",
    )
    store.append_series_state(state)
    found = store.continuations_for("P_1")
    assert len(found) == 1
    assert found[0]["next_stage"] == "formation"
    assert found[0]["participants"][0]["name"] == "小明"


def test_ending_closes_series():
    store = InMemoryStore()
    state = make_series_state(
        group_series_id="series_1",
        participant_id="P_1",
        completed_stage="ending",
        role_mode="member",
        group_type="生涯團體",
        school_id="sfbt",
        school_name="焦點解決短期治療 SFBT",
        base_context="",
        participants=[],
        member_states={},
        prior_summary={},
        carryover_context="",
    )
    store.append_series_state(state)
    assert store.continuations_for("P_1") == []

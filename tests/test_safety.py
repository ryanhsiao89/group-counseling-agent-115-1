from src.safety import detect_immediate_risk


def test_immediate_first_person_risk_is_detected():
    assert detect_immediate_risk("我今晚想自殺")
    assert detect_immediate_risk("我已經吞藥")


def test_general_academic_discussion_is_not_automatically_blocked():
    assert not detect_immediate_risk("今天課堂討論自殺防治的重要性")

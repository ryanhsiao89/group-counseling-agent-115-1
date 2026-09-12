from src.auth import generate_otp, hash_otp, is_allowed_email, make_participant_id, verify_otp


def test_email_rules_include_school_and_teacher_exception():
    teachers = ("ryanhsiao89@gmail.com",)
    assert is_allowed_email("Student@hcu.edu.tw", "hcu.edu.tw", teachers)
    assert is_allowed_email("RYANHSIAO89@GMAIL.COM", "hcu.edu.tw", teachers)
    assert not is_allowed_email("person@gmail.com", "hcu.edu.tw", teachers)


def test_participant_id_is_stable_and_email_is_not_exposed():
    value = make_participant_id("student@hcu.edu.tw", "a-long-private-salt")
    assert value == make_participant_id("STUDENT@HCU.EDU.TW", "a-long-private-salt")
    assert "student" not in value


def test_otp_hash_verification():
    otp = generate_otp()
    assert len(otp) == 6 and otp.isdigit()
    digest = hash_otp(otp, "nonce")
    assert verify_otp(otp, digest, "nonce")
    assert not verify_otp("000000" if otp != "000000" else "111111", digest, "nonce")

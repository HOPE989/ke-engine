from app.core.security import get_password_hash, verify_password


def test_password_hash_verifies_plain_password():
    hashed = get_password_hash("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


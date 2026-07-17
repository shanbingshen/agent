from arthra.security import hash_password, verify_password


def test_password_hash_roundtrip():
    encoded = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", encoded)
    assert not verify_password("wrong", encoded)
    assert "correct-horse" not in encoded


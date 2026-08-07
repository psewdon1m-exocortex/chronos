from __future__ import annotations

from app.security import (
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)


def test_session_token_checks_generation_signature_and_expiry() -> None:
    secret = "s" * 40
    token = create_session_token(secret, 4, "csrf-value", now=1_000)
    payload = verify_session_token(token, secret, 4, now=1_001)
    assert payload and payload["csrf"] == "csrf-value"
    assert verify_session_token(token, secret, 5, now=1_001) is None
    assert verify_session_token(token, "x" * 40, 4, now=1_001) is None
    assert verify_session_token(token, secret, 4, now=1_000 + 12 * 60 * 60) is None


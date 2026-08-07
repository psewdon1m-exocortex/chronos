from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from typing import Any


SESSION_TTL_SECONDS = 12 * 60 * 60
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=64,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt${_b64encode(salt)}${_b64encode(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_value, expected_value = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        salt = _b64decode(salt_value)
        expected = _b64decode(expected_value)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=16384,
            r=8,
            p=1,
            dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_session_token(
    secret: str,
    generation: int,
    csrf: str,
    now: int | None = None,
) -> str:
    issued_at = now or int(time.time())
    payload = {
        "sub": "operator",
        "generation": generation,
        "csrf": csrf,
        "issued_at": issued_at,
        "expires_at": issued_at + SESSION_TTL_SECONDS,
    }
    encoded = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = _b64encode(
        hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{encoded}.{signature}"


def verify_session_token(
    token: str | None,
    secret: str,
    generation: int,
    now: int | None = None,
) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        encoded, signature = token.split(".", 1)
        expected = _b64encode(
            hmac.new(
                secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
        current = now or int(time.time())
        if (
            payload.get("sub") != "operator"
            or payload.get("generation") != generation
            or not isinstance(payload.get("expires_at"), int)
            or payload["expires_at"] <= current
        ):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def new_csrf_token() -> str:
    return _b64encode(os.urandom(24))


def new_link_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    entropy = os.urandom(8)
    return "".join(alphabet[value % len(alphabet)] for value in entropy)


def validate_new_password(value: str) -> None:
    if len(value) < 12:
        raise ValueError("Password must contain at least 12 characters")
    if value.lower() in {"change_me", "password", "chronos", "administrator"}:
        raise ValueError("Password is too predictable")


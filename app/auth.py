from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Any, Dict

import jwt
from fastapi import Header, HTTPException


JWT_ALGORITHM = "HS256"
JWT_SECRET = os.getenv("JWT_SECRET", "development-only-change-me-use-env-in-production-2026")


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt, expected = encoded.split("$", 1)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(actual, expected)


def create_token(user_id: str) -> str:
    return jwt.encode({"sub": user_id, "iat": int(time.time()), "exp": int(time.time()) + 86400}, JWT_SECRET, algorithm=JWT_ALGORITHM)


def current_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload: Dict[str, Any] = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return str(payload["sub"])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired bearer token") from exc

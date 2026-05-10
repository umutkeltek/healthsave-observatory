"""Shared FastAPI dependencies (auth, session)."""

import os

from fastapi import Header, HTTPException

from ..db.session import get_session

API_KEY = os.getenv("API_KEY", "")


def verify_api_key(x_api_key: str = Header(default="")):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


__all__ = ["API_KEY", "get_session", "verify_api_key"]

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Optional

from db.supabase_client import get_supabase_client, supabase_configured

_LOCK = threading.Lock()
_MEMORY: dict[str, dict[str, Any]] = {}


def get_session(session_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        cached = _MEMORY.get(session_id)
    if cached is not None:
        return cached
    if not supabase_configured():
        return None
    try:
        response = (
            get_supabase_client()
            .table("agent_sessions")
            .select("*")
            .eq("session_id", session_id)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    rows = response.data or []
    if not rows:
        return None
    session = _from_row(rows[0])
    with _LOCK:
        _MEMORY[session_id] = session
    return session


def save_session(session: dict[str, Any]) -> None:
    session_id = str(session["session_id"])
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        _MEMORY[session_id] = session
    if not supabase_configured():
        return
    try:
        get_supabase_client().table("agent_sessions").upsert(
            {
                "session_id": session_id,
                "facts": session.get("facts") or {},
                "messages": session.get("messages") or [],
                "updated_at": session["updated_at"],
            },
            on_conflict="session_id",
        ).execute()
    except Exception:
        return


def new_session(session_id: str) -> dict[str, Any]:
    session = {
        "session_id": session_id,
        "facts": {},
        "messages": [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_session(session)
    return session


def _from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": row.get("session_id"),
        "facts": row.get("facts") or {},
        "messages": row.get("messages") or [],
        "updated_at": row.get("updated_at"),
    }

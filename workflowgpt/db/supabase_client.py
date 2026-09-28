from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

from supabase import Client, create_client

from config import SUPABASE_KEY, SUPABASE_URL
from schemas.models import PipelineState

_LIST_COLUMNS = (
    "request_id,raw_instruction,n8n_workflow_id,status,errors,created_at,updated_at"
)


class SupabaseConfigError(RuntimeError):
    """Raised when Supabase credentials are missing or invalid."""


def supabase_configured() -> bool:
    return bool((SUPABASE_URL or "").strip() and (SUPABASE_KEY or "").strip())


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Initialize and cache a Supabase client from config."""
    url = (SUPABASE_URL or "").strip()
    key = (SUPABASE_KEY or "").strip()
    if not url or not key:
        raise SupabaseConfigError(
            "SUPABASE_URL and SUPABASE_KEY must be set in the environment"
        )
    return create_client(url, key)


def workflow_row(state: PipelineState) -> dict[str, Any]:
    """Row written to public.workflows."""
    return {
        "request_id": state.request_id,
        "raw_instruction": state.raw_instruction,
        "workflow_spec": state.workflow_spec,
        "n8n_workflow_json": state.n8n_workflow_json,
        "n8n_workflow_id": state.n8n_workflow_id,
        "status": state.deployment_status,
        "errors": list(state.errors),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_workflow(state: PipelineState) -> dict[str, Any]:
    """Upsert a pipeline run into workflows and optionally log the test result."""
    client = get_supabase_client()
    row = workflow_row(state)
    workflow_response = (
        client.table("workflows")
        .upsert(row, on_conflict="request_id")
        .execute()
    )

    execution_response = None
    if state.test_result is not None:
        execution_response = (
            client.table("execution_logs")
            .insert(
                {
                    "request_id": state.request_id,
                    "test_result": state.test_result,
                }
            )
            .execute()
        )

    return {
        "workflow": workflow_response.data,
        "execution_log": None if execution_response is None else execution_response.data,
    }


def update_workflow_status(request_id: str, status: str) -> dict[str, Any]:
    """Update the status column for a workflow row by request_id."""
    client = get_supabase_client()
    response = (
        client.table("workflows")
        .update({"status": status})
        .eq("request_id", request_id)
        .execute()
    )
    return {"data": response.data}


def get_workflow(request_id: str) -> Optional[dict[str, Any]]:
    """Return one workflow row, or None when it does not exist."""
    client = get_supabase_client()
    response = (
        client.table("workflows")
        .select("*")
        .eq("request_id", request_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return None
    return rows[0]


def list_workflows(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent workflow rows without the full n8n JSON payload."""
    client = get_supabase_client()
    bounded = min(max(limit, 1), 200)
    response = (
        client.table("workflows")
        .select(_LIST_COLUMNS)
        .order("created_at", desc=True)
        .limit(bounded)
        .execute()
    )
    return list(response.data or [])


def delete_workflow_record(request_id: str) -> None:
    """Delete a workflow row. execution_logs cascade with the foreign key."""
    client = get_supabase_client()
    client.table("workflows").delete().eq("request_id", request_id).execute()


def log_error(
    request_id: str,
    error: str,
    raw_instruction: str = "",
) -> dict[str, Any]:
    """Upsert a workflow row, then record the error in execution_logs."""
    client = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()
    workflow_response = (
        client.table("workflows")
        .upsert(
            {
                "request_id": request_id,
                "raw_instruction": raw_instruction or "(unknown)",
                "status": "error",
                "errors": [error],
                "updated_at": now,
            },
            on_conflict="request_id",
        )
        .execute()
    )
    log_response = (
        client.table("execution_logs")
        .insert(
            {
                "request_id": request_id,
                "test_result": {"error": error},
            }
        )
        .execute()
    )
    return {
        "execution_log": log_response.data,
        "workflow": workflow_response.data,
    }

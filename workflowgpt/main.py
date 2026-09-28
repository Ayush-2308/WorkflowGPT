from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agents.deployer_agent import N8nDeployError, delete_remote_workflow
from config import (
    LLM_PROVIDER,
    N8N_API_KEY,
    N8N_BASE_URL,
    WORKFLOWGPT_API_KEY,
    missing_settings,
)
from db.supabase_client import (
    SupabaseConfigError,
    delete_workflow_record,
    get_workflow,
    list_workflows,
    log_error,
)
from db.sessions import get_session, new_session, save_session
from graph import run_pipeline
from schemas.models import PipelineState

app = FastAPI(
    title="WorkflowGPT",
    description="Turn natural-language instructions into deployed n8n workflows.",
)


class GenerateWorkflowRequest(BaseModel):
    instruction: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    answers: dict[str, str] = Field(default_factory=dict)


class AgentTurnRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    answers: dict[str, str] = Field(default_factory=dict)


class GenerateWorkflowResponse(PipelineState):
    n8n_workflow_url: Optional[str] = None


def require_api_key(request: Request) -> None:
    expected = (WORKFLOWGPT_API_KEY or "").strip()
    if not expected:
        return
    provided = request.headers.get("X-API-Key", "").strip()
    authorization = request.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        provided = provided or authorization[7:].strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="invalid api key")


def _n8n_workflow_url(workflow_id: str | None) -> str | None:
    if not workflow_id:
        return None
    base = (N8N_BASE_URL or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/workflow/{workflow_id}"


def _public_payload(state: PipelineState) -> dict[str, Any]:
    payload = state.model_dump()
    payload["n8n_workflow_url"] = _n8n_workflow_url(state.n8n_workflow_id)
    payload["facts"] = {
        key: ("••••" if _is_secret_key(key) else value)
        for key, value in (state.facts or {}).items()
    }
    return payload


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        token in lowered
        for token in ("token", "secret", "password", "key", "authorization", "cookie")
    )


def _run_from_user_input(
    message: str,
    session_id: str | None,
    answers: dict[str, str],
) -> PipelineState:
    sid = session_id or str(uuid.uuid4())
    session = get_session(sid) or new_session(sid)
    facts = dict(session.get("facts") or {})
    for key, value in (answers or {}).items():
        if str(value).strip():
            facts[str(key)] = str(value).strip()
    messages = list(session.get("messages") or [])
    messages.append({"role": "user", "content": message})
    state = run_pipeline(
        message,
        session_id=sid,
        facts=facts,
        conversation=messages[:-1],
    )
    state.session_id = sid
    assistant = state.assistant_message or ""
    if state.questions:
        prompts = " ".join(str(item.get("prompt") or "") for item in state.questions)
        assistant = assistant or prompts
    if assistant:
        messages.append({"role": "assistant", "content": assistant})
    session["facts"] = dict(state.facts or facts)
    session["messages"] = messages[-40:]
    save_session(session)
    return state


def _supabase_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SupabaseConfigError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    page = Path(__file__).resolve().parent / "static" / "index.html"
    return page.read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict[str, Any]:
    missing = missing_settings()
    return {
        "status": "ok" if not missing else "incomplete",
        "missing": missing,
        "llm_provider": (LLM_PROVIDER or "anthropic").strip() or "anthropic",
        "llm_configured": "LLM_API_KEY" not in missing,
        "n8n_configured": "N8N_API_KEY" not in missing and "N8N_BASE_URL" not in missing,
        "supabase_configured": "SUPABASE_URL" not in missing and "SUPABASE_KEY" not in missing,
        "auth_required": bool((WORKFLOWGPT_API_KEY or "").strip()),
    }


@app.post(
    "/generate-workflow",
    response_model=GenerateWorkflowResponse,
    dependencies=[Depends(require_api_key)],
)
def generate_workflow(body: GenerateWorkflowRequest) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    try:
        state = _run_from_user_input(body.instruction, body.session_id, body.answers)
        state.request_id = state.request_id or request_id
    except Exception as exc:  # noqa: BLE001 - return a controlled API error
        try:
            log_error(request_id, str(exc), raw_instruction=body.instruction)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail={
                "request_id": request_id,
                "error": str(exc),
            },
        ) from exc
    return _public_payload(state)


@app.post("/agent", dependencies=[Depends(require_api_key)])
def agent_turn(body: AgentTurnRequest) -> dict[str, Any]:
    try:
        state = _run_from_user_input(body.message, body.session_id, body.answers)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return _public_payload(state)


@app.get("/workflows", dependencies=[Depends(require_api_key)])
def get_workflows(limit: int = 50) -> dict[str, Any]:
    try:
        rows = list_workflows(limit)
    except Exception as exc:  # noqa: BLE001
        raise _supabase_http_error(exc) from exc
    return {
        "workflows": [
            {**row, "n8n_workflow_url": _n8n_workflow_url(row.get("n8n_workflow_id"))}
            for row in rows
        ]
    }


@app.get("/workflows/{request_id}", dependencies=[Depends(require_api_key)])
def get_workflow_by_id(request_id: str) -> dict[str, Any]:
    try:
        row = get_workflow(request_id)
    except Exception as exc:  # noqa: BLE001
        raise _supabase_http_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    row["n8n_workflow_url"] = _n8n_workflow_url(row.get("n8n_workflow_id"))
    return row


@app.delete("/workflows/{request_id}", dependencies=[Depends(require_api_key)])
def delete_workflow(request_id: str) -> dict[str, Any]:
    try:
        row = get_workflow(request_id)
    except Exception as exc:  # noqa: BLE001
        raise _supabase_http_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="workflow not found")

    n8n_deleted = False
    workflow_id = row.get("n8n_workflow_id")
    if workflow_id:
        try:
            delete_remote_workflow(
                str(workflow_id),
                (N8N_BASE_URL or "").strip(),
                (N8N_API_KEY or "").strip(),
            )
            n8n_deleted = True
        except N8nDeployError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        delete_workflow_record(request_id)
    except Exception as exc:  # noqa: BLE001
        raise _supabase_http_error(exc) from exc
    return {
        "request_id": request_id,
        "n8n_deleted": n8n_deleted,
    }

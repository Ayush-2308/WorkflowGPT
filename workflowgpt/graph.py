from __future__ import annotations

import uuid
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from agents.builder_agent import build_n8n_workflow
from agents.credential_apply import apply_planned_credentials
from agents.deployer_agent import N8nDeployError, deploy_workflow
from agents.executor_agent import N8nExecutorError, test_workflow
from agents.parser_agent import parse_instruction
from agents.planner_agent import plan_turn
from config import N8N_API_KEY, N8N_BASE_URL
from db.supabase_client import save_workflow, supabase_configured
from schemas.models import PipelineState, WorkflowSpec


def parse_node(state: PipelineState) -> dict[str, Any]:
    """Plan the automation: ask for missing inputs or produce n8n JSON."""
    message = state.raw_instruction
    if state.conversation:
        last = state.conversation[-1]
        if last.get("role") == "user" and last.get("content"):
            message = last["content"]
    try:
        plan = plan_turn(message, list(state.conversation), dict(state.facts))
    except Exception as exc:  # noqa: BLE001
        try:
            spec = parse_instruction(state.raw_instruction)
        except Exception as parse_exc:  # noqa: BLE001
            message_text = f"parse failed after validation retry: {exc}; {parse_exc}"
            return {
                "workflow_spec": None,
                "deployment_status": "parse_failed",
                "assistant_message": "I could not plan this automation yet.",
                "errors": _append_error(state, message_text),
            }
        return {
            "workflow_spec": spec.model_dump(),
            "deployment_status": "parsed",
            "facts": dict(state.facts),
            "errors": list(state.errors),
        }

    updates: dict[str, Any] = {
        "facts": plan.facts,
        "questions": [item.model_dump() for item in plan.questions],
        "assistant_message": plan.assistant_message,
        "errors": list(state.errors),
    }
    if plan.mode == "ask":
        updates["deployment_status"] = "needs_input"
        return updates
    if plan.n8n_workflow:
        workflow = plan.n8n_workflow
        base_url = (N8N_BASE_URL or "").strip()
        api_key = (N8N_API_KEY or "").strip()
        if plan.credentials and base_url and api_key:
            apply_planned_credentials(
                workflow, plan.credentials, plan.facts, base_url, api_key
            )
        updates["n8n_workflow_json"] = workflow
        updates["deployment_status"] = "built"
        return updates
    if plan.workflow_spec:
        updates["workflow_spec"] = plan.workflow_spec
        updates["deployment_status"] = "parsed"
        return updates
    updates["deployment_status"] = "needs_input"
    return updates


def build_node(state: PipelineState) -> dict[str, Any]:
    if not state.workflow_spec:
        return {
            "deployment_status": "build_failed",
            "errors": _append_error(state, "build skipped: missing workflow_spec"),
        }

    try:
        spec = WorkflowSpec.model_validate(state.workflow_spec)
        workflow_json = build_n8n_workflow(spec)
    except Exception as exc:  # noqa: BLE001
        return {
            "deployment_status": "build_failed",
            "errors": _append_error(state, f"build failed: {exc}"),
        }
    return {
        "n8n_workflow_json": workflow_json,
        "deployment_status": "built",
    }


def deploy_node(state: PipelineState) -> dict[str, Any]:
    if not state.n8n_workflow_json:
        message = "deploy skipped: missing n8n_workflow_json"
        print(f"[deploy] {message}")
        return {
            "deployment_status": "deployment_failed",
            "errors": _append_error(state, message),
        }

    base_url = (N8N_BASE_URL or "").strip()
    api_key = (N8N_API_KEY or "").strip()
    if not base_url or not api_key:
        message = "deploy skipped: set N8N_BASE_URL and N8N_API_KEY in workflowgpt/.env"
        print(f"[deploy] {message}")
        return {
            "deployment_status": "deploy_skipped",
            "errors": _append_error(state, message),
        }
    try:
        workflow_id = deploy_workflow(state.n8n_workflow_json, base_url, api_key)
    except N8nDeployError as exc:
        message = f"deployment failed: {exc}"
        print(f"[deploy] {message}")
        return {
            "n8n_workflow_id": None,
            "deployment_status": "deployment_failed",
            "errors": _append_error(state, message),
        }
    except Exception as exc:  # noqa: BLE001
        message = f"deployment failed: {exc}"
        print(f"[deploy] {message}")
        return {
            "n8n_workflow_id": None,
            "deployment_status": "deployment_failed",
            "errors": _append_error(state, message),
        }

    return {
        "n8n_workflow_id": workflow_id,
        "deployment_status": "deployed",
    }


def test_node(state: PipelineState) -> dict[str, Any]:
    if not state.n8n_workflow_id:
        return {
            "deployment_status": "deployment_failed",
            "errors": _append_error(state, "test skipped: missing n8n_workflow_id"),
        }

    base_url = (N8N_BASE_URL or "").strip()
    api_key = (N8N_API_KEY or "").strip()
    sample_payload = _sample_payload(state)
    try:
        result = test_workflow(
            n8n_workflow_id=state.n8n_workflow_id,
            n8n_base_url=base_url,
            n8n_api_key=api_key,
            sample_payload=sample_payload,
        )
    except N8nExecutorError as exc:
        message = f"test failed: {exc}"
        return {
            "test_result": {"status": "error", "error": str(exc)},
            "deployment_status": "test_failed",
            "errors": _append_error(state, message),
        }

    if result.get("status") == "skipped":
        return {
            "test_result": result,
            "deployment_status": "test_skipped",
            "errors": _append_error(state, str(result.get("reason") or "test skipped")),
        }

    return {
        "test_result": result,
        "deployment_status": "tested",
    }


def persist_node(state: PipelineState) -> dict[str, Any]:
    """Persist whatever the pipeline reached, including failures."""
    final_status = resolve_persisted_status(state.deployment_status)
    snapshot = state.model_copy(update={"deployment_status": final_status})
    if final_status not in {"completed", "needs_input"}:
        print(f"[{final_status}] request_id={state.request_id} errors={state.errors}")
    if not supabase_configured():
        if final_status == "needs_input":
            return {"deployment_status": final_status}
        message = (
            "store skipped: set SUPABASE_URL and SUPABASE_KEY in workflowgpt/.env, "
            "then run migrations.sql in the Supabase SQL editor"
        )
        print(f"[persist] {message}")
        return {
            "deployment_status": final_status,
            "errors": _append_error(state, message),
        }
    try:
        save_workflow(snapshot)
    except Exception as exc:  # noqa: BLE001 - keep pipeline resilient on store errors
        message = f"store failed: {exc}"
        return {
            "deployment_status": "store_failed",
            "errors": _append_error(state, message),
        }
    return {"deployment_status": final_status}


def resolve_persisted_status(status: str) -> str:
    """A successful test is the only status promoted to completed."""
    if status == "tested":
        return "completed"
    return status


def route_after_parse(state: PipelineState) -> Literal["build", "deploy", "persist"]:
    if state.deployment_status == "needs_input":
        return "persist"
    if state.deployment_status == "parse_failed" or (
        not state.workflow_spec and not state.n8n_workflow_json
    ):
        return "persist"
    if state.n8n_workflow_json and state.deployment_status == "built":
        return "deploy"
    return "build"


def route_after_build(state: PipelineState) -> Literal["deploy", "persist"]:
    if state.deployment_status == "build_failed" or not state.n8n_workflow_json:
        return "persist"
    return "deploy"


def route_after_deploy(state: PipelineState) -> Literal["test", "persist"]:
    if state.deployment_status in {"deployment_failed", "deploy_skipped"} or not state.n8n_workflow_id:
        return "persist"
    return "test"


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("parse", parse_node)
    graph.add_node("build", build_node)
    graph.add_node("deploy", deploy_node)
    graph.add_node("test", test_node)
    graph.add_node("persist", persist_node)

    graph.add_edge(START, "parse")
    graph.add_conditional_edges(
        "parse",
        route_after_parse,
        {
            "build": "build",
            "deploy": "deploy",
            "persist": "persist",
        },
    )
    graph.add_conditional_edges(
        "build",
        route_after_build,
        {
            "deploy": "deploy",
            "persist": "persist",
        },
    )
    graph.add_conditional_edges(
        "deploy",
        route_after_deploy,
        {
            "test": "test",
            "persist": "persist",
        },
    )
    graph.add_edge("test", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


pipeline_graph = build_graph()


def run_pipeline(
    raw_instruction: str,
    request_id: str | None = None,
    *,
    session_id: str | None = None,
    facts: dict[str, Any] | None = None,
    conversation: list[dict[str, str]] | None = None,
) -> PipelineState:
    """Run plan -> build -> deploy -> test -> persist (or stop to ask questions)."""
    initial_facts = facts
    initial = PipelineState(
        request_id=request_id or str(uuid.uuid4()),
        raw_instruction=raw_instruction,
        workflow_spec=None,
        n8n_workflow_json=None,
        n8n_workflow_id=None,
        deployment_status="pending",
        test_result=None,
        errors=[],
        assistant_message=None,
        questions=[],
        facts=initial_facts or {},
        conversation=list(conversation or []),
        session_id=session_id,
    )
    result = pipeline_graph.invoke(initial)
    if isinstance(result, PipelineState):
        return result
    return PipelineState.model_validate(result)


def _sample_payload(state: PipelineState) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": "workflowgpt",
        "request_id": state.request_id,
        "instruction": state.raw_instruction,
    }
    spec = state.workflow_spec or {}
    trigger = spec.get("trigger") if isinstance(spec, dict) else None
    config = trigger.get("config") if isinstance(trigger, dict) else None
    if isinstance(config, dict):
        fields = config.get("fields") or []
        if isinstance(fields, list):
            for field in fields:
                if isinstance(field, str) and field not in payload:
                    payload[field] = f"sample_{field}"
                elif isinstance(field, dict):
                    name = field.get("name") or field.get("fieldLabel") or field.get("label")
                    if isinstance(name, str) and name not in payload:
                        payload[name] = field.get("example") or f"sample_{name}"
    if "email" not in payload and "email" in state.raw_instruction.lower():
        payload["email"] = "user@example.com"
    return payload


def _append_error(state: PipelineState, message: str) -> list[str]:
    errors = list(state.errors)
    errors.append(message)
    return errors

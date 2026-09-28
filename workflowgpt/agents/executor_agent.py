from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlencode

import httpx

_API_KEY_HEADER = "X-N8N-API-KEY"
_DEFAULT_POLL_ATTEMPTS = 20
_DEFAULT_POLL_INTERVAL_SEC = 0.75


class N8nExecutorError(RuntimeError):
    """Raised when triggering or polling an n8n workflow execution fails."""


def test_workflow(
    n8n_workflow_id: str,
    n8n_base_url: str,
    n8n_api_key: str,
    sample_payload: dict[str, Any],
) -> dict[str, Any]:
    """Trigger a deployed workflow webhook and poll until an execution settles."""
    if not n8n_workflow_id or not str(n8n_workflow_id).strip():
        raise N8nExecutorError("n8n_workflow_id is required")
    if not n8n_base_url or not str(n8n_base_url).strip():
        raise N8nExecutorError("n8n_base_url is required (e.g. http://localhost:5678)")
    if not n8n_api_key or not str(n8n_api_key).strip():
        raise N8nExecutorError("n8n_api_key is required")

    base_url = n8n_base_url.strip().rstrip("/")
    api_key = n8n_api_key.strip()
    workflow_id = str(n8n_workflow_id).strip()

    workflow = _api_request(
        method="GET",
        url=_join_url(base_url, f"/api/v1/workflows/{workflow_id}"),
        api_key=api_key,
        action=f"fetch workflow {workflow_id}",
    )
    target = _extract_trigger_target(workflow)
    if target is None:
        return {
            "status": "skipped",
            "execution_id": None,
            "finished": False,
            "reason": (
                "n8n's public API cannot execute a workflow that has no webhook "
                "or form trigger. Activate the workflow and run it from the n8n editor."
            ),
            "sample_payload": sample_payload,
        }
    path, http_method, body_mode = target
    prefix = "/form/" if body_mode == "form" else "/webhook/"
    trigger_url = _join_url(base_url, f"{prefix}{path}")

    triggered_at = time.time()
    webhook_response = _trigger_webhook(
        url=trigger_url,
        method=http_method,
        payload=sample_payload,
        body_mode=body_mode,
    )

    execution = _poll_latest_execution(
        base_url=base_url,
        api_key=api_key,
        workflow_id=workflow_id,
        triggered_at=triggered_at,
    )

    return {
        "status": execution.get("status") or ("success" if execution else "unknown"),
        "execution_id": execution.get("id"),
        "finished": bool(execution.get("finished", execution.get("status") == "success")),
        "webhook": {
            "url": trigger_url,
            "method": http_method,
            "response_status": webhook_response.get("status_code"),
            "response_body": webhook_response.get("body"),
        },
        "execution": execution,
        "sample_payload": sample_payload,
    }


def _workflow_nodes(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = workflow.get("nodes") or []
    if isinstance(workflow.get("data"), dict):
        nodes = workflow["data"].get("nodes") or nodes
    return [node for node in nodes if isinstance(node, dict)]


def _extract_webhook_target(workflow: dict[str, Any]) -> tuple[str, str]:
    """Return the webhook path and HTTP method, preferring the test webhook."""
    matches: list[tuple[str, str, bool]] = []
    for node in _workflow_nodes(workflow):
        node_type = str(node.get("type") or "")
        if "webhook" not in node_type.lower() or "form" in node_type.lower():
            continue
        params = node.get("parameters") or {}
        path = params.get("path") or params.get("webhookId") or node.get("webhookId")
        if not path:
            continue
        method = str(params.get("httpMethod") or params.get("method") or "POST").upper()
        preferred = str(node.get("name") or "").lower().startswith("test_")
        matches.append((str(path).strip().strip("/"), method, preferred))
    if not matches:
        raise N8nExecutorError(
            f"Workflow has no webhook trigger node to test: {workflow.get('id')}"
        )
    matches.sort(key=lambda item: item[2], reverse=True)
    path, method, _preferred = matches[0]
    return path, method


def _extract_form_target(workflow: dict[str, Any]) -> tuple[str, str] | None:
    for node in _workflow_nodes(workflow):
        node_type = str(node.get("type") or "")
        if "formtrigger" not in node_type.lower():
            continue
        params = node.get("parameters") or {}
        path = params.get("path") or node.get("webhookId")
        if not path:
            continue
        return str(path).strip().strip("/"), "POST"
    return None


def _extract_trigger_target(
    workflow: dict[str, Any],
) -> tuple[str, str, str] | None:
    """Return (absolute-or-relative path, method, body mode) for a runnable trigger."""
    try:
        path, method = _extract_webhook_target(workflow)
    except N8nExecutorError:
        form = _extract_form_target(workflow)
        if form is None:
            return None
        path, method = form
        return path, method, "form"
    return path, method, "json"


def _trigger_webhook(
    url: str,
    method: str,
    payload: dict[str, Any],
    body_mode: str = "json",
) -> dict[str, Any]:
    request_kwargs: dict[str, Any]
    if body_mode == "form":
        request_kwargs = {
            "data": {
                str(key): value if isinstance(value, str) else json.dumps(value)
                for key, value in payload.items()
            }
        }
    else:
        request_kwargs = {"json": payload}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method=method.upper(),
                url=url,
                headers={"Accept": "application/json"},
                **request_kwargs,
            )
    except httpx.HTTPError as exc:
        raise N8nExecutorError(f"webhook trigger request failed: {exc}") from exc

    body: Any
    try:
        body = response.json()
    except ValueError:
        body = response.text

    if response.is_error:
        raise N8nExecutorError(
            f"webhook trigger failed with status {response.status_code}: {body}"
        )

    return {"status_code": response.status_code, "body": body}


def _poll_latest_execution(
    base_url: str,
    api_key: str,
    workflow_id: str,
    triggered_at: float,
) -> dict[str, Any]:
    query = urlencode({"workflowId": workflow_id, "limit": 5, "includeData": "true"})
    list_url = _join_url(base_url, f"/api/v1/executions?{query}")

    last_seen: dict[str, Any] | None = None
    for _ in range(_DEFAULT_POLL_ATTEMPTS):
        payload = _api_request(
            method="GET",
            url=list_url,
            api_key=api_key,
            action=f"list executions for workflow {workflow_id}",
        )
        executions = _normalize_execution_list(payload)
        candidate = _pick_recent_execution(executions, triggered_at)
        if candidate is not None:
            last_seen = candidate
            status = str(candidate.get("status") or "").lower()
            if status not in {"running", "waiting", "new"} and (
                candidate.get("finished") is True or status in {"success", "error", "canceled", "crashed"}
            ):
                return candidate
            if candidate.get("id") is not None and status in {"running", "waiting", "new"}:
                detail = _api_request(
                    method="GET",
                    url=_join_url(
                        base_url,
                        f"/api/v1/executions/{candidate['id']}?includeData=true",
                    ),
                    api_key=api_key,
                    action=f"get execution {candidate['id']}",
                )
                last_seen = detail
                detail_status = str(detail.get("status") or "").lower()
                if detail_status not in {"running", "waiting", "new"}:
                    return detail
        time.sleep(_DEFAULT_POLL_INTERVAL_SEC)

    if last_seen is not None:
        return last_seen
    raise N8nExecutorError(
        f"Timed out waiting for execution of workflow {workflow_id}"
    )


def _normalize_execution_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return [item for item in data["results"] if isinstance(item, dict)]
    return []


def _pick_recent_execution(
    executions: list[dict[str, Any]],
    triggered_at: float,
) -> dict[str, Any] | None:
    if not executions:
        return None

    def sort_key(item: dict[str, Any]) -> str:
        return str(item.get("startedAt") or item.get("stoppedAt") or item.get("id") or "")

    ordered = sorted(executions, key=sort_key, reverse=True)
    for item in ordered:
        started = _parse_epoch(item.get("startedAt"))
        if started is None or started + 2.0 >= triggered_at:
            return item
    return ordered[0]


def _parse_epoch(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        # Handle trailing Z without depending on datetime extras.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        from datetime import datetime

        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _api_request(
    method: str,
    url: str,
    api_key: str,
    action: str,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        _API_KEY_HEADER: api_key,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
            )
    except httpx.HTTPError as exc:
        raise N8nExecutorError(f"n8n {action} request failed: {exc}") from exc

    if response.is_error:
        raise N8nExecutorError(
            f"n8n {action} failed with status {response.status_code}: {response.text}"
        )

    if not response.content:
        return {}
    try:
        data = response.json()
    except ValueError as exc:
        raise N8nExecutorError(
            f"n8n {action} returned non-JSON body: {response.text}"
        ) from exc
    if not isinstance(data, dict):
        raise N8nExecutorError(
            f"n8n {action} returned unexpected JSON type: {type(data).__name__}"
        )
    return data


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

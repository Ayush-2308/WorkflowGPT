from __future__ import annotations

from typing import Any

import httpx

# Self-hosted n8n public API (same path shape as Cloud; only the host differs).
_CREATE_PATH = "/api/v1/workflows"
_ACTIVATE_PATH = "/api/v1/workflows/{workflow_id}/activate"
_API_KEY_HEADER = "X-N8N-API-KEY"


class N8nDeployError(RuntimeError):
    """Raised when an n8n deploy/activate API call fails."""


def deploy_workflow(
    workflow_json: dict[str, Any],
    n8n_base_url: str,
    n8n_api_key: str,
) -> str:
    """Create a workflow in n8n, activate it, and return the workflow ID.

    Expects a self-hosted base URL such as ``http://localhost:5678``
    (no ``/api/v1`` suffix). Auth uses the ``X-N8N-API-KEY`` header.
    """
    if not n8n_base_url or not str(n8n_base_url).strip():
        raise N8nDeployError("n8n_base_url is required (e.g. http://localhost:5678)")
    if not n8n_api_key or not str(n8n_api_key).strip():
        raise N8nDeployError("n8n_api_key is required")

    return _create_and_activate(workflow_json, n8n_base_url.strip(), n8n_api_key.strip())


def _create_and_activate(
    workflow_json: dict[str, Any],
    n8n_base_url: str,
    n8n_api_key: str,
) -> str:
    create_url = _join_url(n8n_base_url, _CREATE_PATH)
    payload = _workflow_create_payload(workflow_json)

    create_response = _request(
        method="POST",
        url=create_url,
        n8n_api_key=n8n_api_key,
        json_body=payload,
        action="create workflow",
    )
    workflow_id = _extract_workflow_id(create_response)

    activate_url = _join_url(
        n8n_base_url,
        _ACTIVATE_PATH.format(workflow_id=workflow_id),
    )
    _request(
        method="POST",
        url=activate_url,
        n8n_api_key=n8n_api_key,
        json_body={},
        action=f"activate workflow {workflow_id}",
    )
    return workflow_id


def _request(
    method: str,
    url: str,
    n8n_api_key: str,
    json_body: dict[str, Any] | None,
    action: str,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        _API_KEY_HEADER: n8n_api_key,
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
        raise N8nDeployError(f"n8n {action} request failed: {exc}") from exc

    if response.is_error:
        body = response.text
        raise N8nDeployError(
            f"n8n {action} failed with status {response.status_code}: {body}"
        )

    if not response.content:
        return {}
    try:
        data = response.json()
    except ValueError as exc:
        raise N8nDeployError(
            f"n8n {action} returned non-JSON body: {response.text}"
        ) from exc
    if not isinstance(data, dict):
        raise N8nDeployError(
            f"n8n {action} returned unexpected JSON type: {type(data).__name__}"
        )
    return data


def _workflow_create_payload(workflow_json: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields commonly accepted by POST /api/v1/workflows."""
    allowed = ("name", "nodes", "connections", "settings", "staticData")
    payload = {key: workflow_json[key] for key in allowed if key in workflow_json}
    payload.setdefault("name", "WorkflowGPT workflow")
    payload.setdefault("nodes", [])
    payload.setdefault("connections", {})
    payload.setdefault("settings", {})
    return payload


def _extract_workflow_id(create_response: dict[str, Any]) -> str:
    workflow_id = create_response.get("id")
    if workflow_id is None and isinstance(create_response.get("data"), dict):
        workflow_id = create_response["data"].get("id")
    if workflow_id is None or str(workflow_id).strip() == "":
        raise N8nDeployError(
            f"n8n create workflow response missing id: {create_response}"
        )
    return str(workflow_id)


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

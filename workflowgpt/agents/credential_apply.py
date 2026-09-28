from __future__ import annotations

from typing import Any

from agents.deployer_agent import N8nDeployError, create_credential
from agents.n8n_sanitize import attach_credential


def apply_planned_credentials(
    workflow: dict[str, Any],
    credential_plans: list[dict[str, Any]],
    facts: dict[str, Any],
    n8n_base_url: str,
    n8n_api_key: str,
) -> list[str]:
    """Create n8n credentials from the plan and attach them to nodes."""
    created: list[str] = []
    for item in credential_plans:
        node_name = str(item.get("node_name") or "")
        cred_type = str(item.get("n8n_type") or "")
        existing_id = item.get("id") or facts.get(f"{item.get('id_fact')}") or facts.get("credential_id")
        name = str(item.get("name") or cred_type or "WorkflowGPT credential")
        if existing_id and node_name:
            attach_credential(workflow, node_name, cred_type or "httpHeaderAuth", str(existing_id), name)
            created.append(str(existing_id))
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if not cred_type or not data:
            continue
        try:
            credential_id = create_credential(name, cred_type, data, n8n_base_url, n8n_api_key)
        except N8nDeployError:
            continue
        created.append(credential_id)
        if node_name:
            attach_credential(workflow, node_name, cred_type, credential_id, name)
    return created

from __future__ import annotations

import uuid
from typing import Any

TYPE_VERSIONS: dict[str, float] = {
    "n8n-nodes-base.webhook": 2,
    "n8n-nodes-base.scheduleTrigger": 1.2,
    "n8n-nodes-base.formTrigger": 2.2,
    "n8n-nodes-base.httpRequest": 4.2,
    "n8n-nodes-base.emailSend": 2.1,
    "n8n-nodes-base.if": 2.2,
    "n8n-nodes-base.code": 2,
    "n8n-nodes-base.set": 3.4,
    "n8n-nodes-base.convertToFile": 1.1,
    "n8n-nodes-base.postgres": 2.5,
    "n8n-nodes-base.mySql": 2.5,
    "n8n-nodes-base.supabase": 1,
    "n8n-nodes-base.slack": 2.2,
    "n8n-nodes-base.telegram": 1.2,
    "n8n-nodes-base.gmail": 2,
    "n8n-nodes-base.googleSheets": 4,
    "n8n-nodes-base.merge": 3,
    "n8n-nodes-base.switch": 3,
}


def sanitize_n8n_workflow(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize LLM-produced n8n JSON into a deployable workflow object."""
    if not isinstance(raw, dict):
        raise ValueError("n8n workflow JSON must be an object")
    payload = raw.get("workflow") if isinstance(raw.get("workflow"), dict) else raw
    if not isinstance(payload, dict):
        raise ValueError("n8n workflow JSON must be an object")

    nodes = payload.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("n8n workflow must include at least one node")

    used_names: set[str] = set()
    clean_nodes: list[dict[str, Any]] = []
    x = 260
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "n8n-nodes-base.code")
        name = _unique_name(str(node.get("name") or f"Node_{index + 1}"), used_names)
        parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
        item: dict[str, Any] = {
            "id": str(node.get("id") or uuid.uuid4()),
            "name": name,
            "type": node_type,
            "typeVersion": node.get("typeVersion") or TYPE_VERSIONS.get(node_type, 1),
            "position": node.get("position") or [x, 300],
            "parameters": parameters,
        }
        x += 280
        if "webhook" in node_type.lower() and "form" not in node_type.lower():
            item["webhookId"] = str(node.get("webhookId") or uuid.uuid4())
            parameters.setdefault("httpMethod", "POST")
            parameters.setdefault("path", parameters.get("path") or "workflowgpt")
            parameters.setdefault("responseMode", "onReceived")
            parameters.setdefault("options", {})
        credentials = node.get("credentials")
        if isinstance(credentials, dict) and credentials:
            item["credentials"] = credentials
        if node.get("notes"):
            item["notes"] = str(node["notes"])
            item["notesInFlow"] = True
        clean_nodes.append(item)

    if not clean_nodes:
        raise ValueError("n8n workflow must include at least one valid node")

    connections = _normalize_connections(payload.get("connections"), clean_nodes)
    name = str(payload.get("name") or "WorkflowGPT automation")
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    settings.setdefault("executionOrder", "v1")
    return {
        "name": name,
        "nodes": clean_nodes,
        "connections": connections,
        "settings": settings,
    }


def attach_credential(workflow: dict[str, Any], node_name: str, credential_type: str, credential_id: str, credential_name: str) -> None:
    for node in workflow.get("nodes") or []:
        if node.get("name") != node_name:
            continue
        node["credentials"] = {
            credential_type: {"id": str(credential_id), "name": credential_name or credential_type}
        }


def _unique_name(raw: str, used: set[str]) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-", " "} else "_" for ch in raw)
    base = " ".join(cleaned.split()) or "Node"
    candidate = base[:48]
    suffix = 2
    while candidate in used:
        candidate = f"{base[:40]}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _normalize_connections(raw: Any, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    names = {node["name"] for node in nodes}
    connections: dict[str, Any] = {}
    if isinstance(raw, dict) and raw:
        for source, value in raw.items():
            if source not in names:
                continue
            mains = []
            if isinstance(value, dict):
                mains = value.get("main") or []
            if not isinstance(mains, list):
                continue
            cleaned_outputs: list[list[dict[str, Any]]] = []
            for output in mains:
                bucket: list[dict[str, Any]] = []
                if isinstance(output, list):
                    for link in output:
                        if not isinstance(link, dict):
                            continue
                        target = str(link.get("node") or "")
                        if target in names:
                            bucket.append({"node": target, "type": "main", "index": 0})
                cleaned_outputs.append(bucket)
            if any(cleaned_outputs):
                connections[source] = {"main": cleaned_outputs or [[]]}
        if connections:
            return connections

    # Linear fallback: connect nodes in listed order.
    for left, right in zip(nodes, nodes[1:]):
        connections.setdefault(left["name"], {"main": [[]]})
        connections[left["name"]]["main"][0].append(
            {"node": right["name"], "type": "main", "index": 0}
        )
    return connections

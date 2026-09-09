from __future__ import annotations

import uuid
from typing import Any

from schemas.models import ActionSpec, TriggerSpec, WorkflowSpec

TRIGGER_NODE_TYPES: dict[str, str] = {
    "webhook": "n8n-nodes-base.webhook",
    "schedule": "n8n-nodes-base.scheduleTrigger",
    "form_submission": "n8n-nodes-base.formTrigger",
}

ACTION_NODE_TYPES: dict[str, str] = {
    "http_request": "n8n-nodes-base.httpRequest",
    "send_email": "n8n-nodes-base.emailSend",
}

CODE_NODE_TYPE = "n8n-nodes-base.code"
DEFAULT_TRIGGER_TYPE = "n8n-nodes-base.webhook"

NODE_X_START = 260
NODE_X_GAP = 280
NODE_Y = 300


def build_n8n_workflow(spec: WorkflowSpec) -> dict[str, Any]:
    """Translate a WorkflowSpec into an n8n workflow export JSON."""
    nodes: list[dict[str, Any]] = []
    connections: dict[str, Any] = {}
    used_names: set[str] = set()

    trigger_node = _build_trigger_node(spec.trigger, spec.name, used_names)
    nodes.append(trigger_node)
    trigger_name = trigger_node["name"]

    action_id_to_name: dict[str, str] = {}
    action_nodes: list[dict[str, Any]] = []

    for index, action in enumerate(spec.actions):
        node = _build_action_node(action, index, used_names)
        action_nodes.append(node)
        nodes.append(node)
        action_id_to_name[_action_key(action, index)] = node["name"]

    for index, action in enumerate(spec.actions):
        target_name = action_nodes[index]["name"]
        source_name = _resolve_source_name(
            action=action,
            index=index,
            trigger_name=trigger_name,
            action_id_to_name=action_id_to_name,
            action_nodes=action_nodes,
        )
        _add_connection(connections, source_name, target_name)

    return {
        "name": spec.name,
        "nodes": nodes,
        "connections": connections,
        "active": False,
        "settings": {
            "executionOrder": "v1",
        },
        "meta": {
            "description": spec.description,
            "raw_instruction": spec.raw_instruction,
            "templateCredsSetupCompleted": False,
        },
        "pinData": {},
        "versionId": str(uuid.uuid4()),
    }


def _build_trigger_node(
    trigger: TriggerSpec,
    workflow_name: str,
    used_names: set[str],
) -> dict[str, Any]:
    node_type = TRIGGER_NODE_TYPES.get(trigger.type.lower(), DEFAULT_TRIGGER_TYPE)
    name = _unique_node_name(f"Trigger_{trigger.type}", used_names)
    parameters = dict(trigger.config)
    notes = None
    if trigger.type.lower() not in TRIGGER_NODE_TYPES:
        notes = (
            f"Unmapped trigger type '{trigger.type}'. "
            f"Using {DEFAULT_TRIGGER_TYPE} as a placeholder."
        )

    node: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": name,
        "type": node_type,
        "typeVersion": 1,
        "position": [NODE_X_START, NODE_Y],
        "parameters": parameters,
    }
    if notes:
        node["notes"] = notes
        node["notesInFlow"] = True
    if node_type == "n8n-nodes-base.webhook":
        node["webhookId"] = str(uuid.uuid4())
        parameters.setdefault("httpMethod", parameters.pop("method", "POST"))
        parameters.setdefault("path", parameters.get("path", _slugify(workflow_name)))
        parameters.setdefault("responseMode", "onReceived")
    return node


def _build_action_node(
    action: ActionSpec,
    index: int,
    used_names: set[str],
) -> dict[str, Any]:
    action_type = action.type.lower()
    mapped_type = ACTION_NODE_TYPES.get(action_type)
    action_key = _action_key(action, index)
    display = action.config.get("id") or action_type
    name = _unique_node_name(f"{index + 1}_{display}", used_names)
    position = [NODE_X_START + NODE_X_GAP * (index + 1), NODE_Y]

    if mapped_type is None:
        return _build_code_placeholder_node(
            name=name,
            position=position,
            action=action,
            action_key=action_key,
        )

    parameters = {
        key: value
        for key, value in action.config.items()
        if key not in {"id", "condition"}
    }
    node: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": name,
        "type": mapped_type,
        "typeVersion": 1,
        "position": position,
        "parameters": parameters,
    }
    if action.config.get("condition"):
        node["notes"] = f"condition: {action.config['condition']}"
        node["notesInFlow"] = True
    return node


def _build_code_placeholder_node(
    name: str,
    position: list[int],
    action: ActionSpec,
    action_key: str,
) -> dict[str, Any]:
    config_comment = ", ".join(
        f"{key}={value!r}" for key, value in action.config.items() if key != "id"
    )
    js_code = "\n".join(
        [
            f"// TODO: Implement action type '{action.type}' (id={action_key})",
            f"// Original config: {config_comment or '{}'}",
            "// Replace this Code node with a real n8n node or fill in the logic.",
            "return items;",
        ]
    )
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "type": CODE_NODE_TYPE,
        "typeVersion": 2,
        "position": position,
        "parameters": {
            "mode": "runOnceForAllItems",
            "language": "javaScript",
            "jsCode": js_code,
        },
        "notes": f"Placeholder for unmapped action type '{action.type}'",
        "notesInFlow": True,
    }


def _resolve_source_name(
    action: ActionSpec,
    index: int,
    trigger_name: str,
    action_id_to_name: dict[str, str],
    action_nodes: list[dict[str, Any]],
) -> str:
    depends_on = (action.depends_on or "").strip()
    if depends_on and depends_on in action_id_to_name:
        return action_id_to_name[depends_on]
    if index > 0:
        return action_nodes[index - 1]["name"]
    return trigger_name


def _add_connection(
    connections: dict[str, Any],
    source_name: str,
    target_name: str,
) -> None:
    source = connections.setdefault(source_name, {"main": [[]]})
    main_outputs: list[list[dict[str, Any]]] = source.setdefault("main", [[]])
    if not main_outputs:
        main_outputs.append([])
    main_outputs[0].append(
        {
            "node": target_name,
            "type": "main",
            "index": 0,
        }
    )


def _action_key(action: ActionSpec, index: int) -> str:
    configured = action.config.get("id")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return f"action_{index + 1}"


def _unique_node_name(raw: str, used_names: set[str]) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-", " "} else "_" for ch in raw)
    cleaned = " ".join(cleaned.split()) or "Node"
    base = cleaned[:48]
    candidate = base
    suffix = 2
    while candidate in used_names:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used_names.add(candidate)
    return candidate


def _slugify(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "workflow"

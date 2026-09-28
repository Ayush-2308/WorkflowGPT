from __future__ import annotations

import copy
import json
import uuid
from typing import Any

from agents.expressions import (
    expression_to_js,
    parse_condition,
    to_n8n_json_body,
    translate_value,
)
from schemas.models import ActionSpec, TriggerSpec, WorkflowSpec

TRIGGER_NODE_TYPES: dict[str, str] = {
    "webhook": "n8n-nodes-base.webhook",
    "schedule": "n8n-nodes-base.scheduleTrigger",
    "form_submission": "n8n-nodes-base.formTrigger",
}

ACTION_NODE_TYPES: dict[str, str] = {
    "http_request": "n8n-nodes-base.httpRequest",
    "send_email": "n8n-nodes-base.emailSend",
    "generate_document": "n8n-nodes-base.convertToFile",
    "database_insert": "n8n-nodes-base.postgres",
}

TYPE_VERSIONS: dict[str, float] = {
    "n8n-nodes-base.webhook": 2,
    "n8n-nodes-base.scheduleTrigger": 1.2,
    "n8n-nodes-base.formTrigger": 2.2,
    "n8n-nodes-base.httpRequest": 4.2,
    "n8n-nodes-base.emailSend": 2.1,
    "n8n-nodes-base.if": 2.2,
    "n8n-nodes-base.code": 2,
    "n8n-nodes-base.convertToFile": 1.1,
    "n8n-nodes-base.postgres": 2.5,
    "n8n-nodes-base.mySql": 2.5,
    "n8n-nodes-base.supabase": 1,
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
    cursor = {"x": NODE_X_START}

    trigger_node = _build_trigger_node(spec.trigger, spec.name, used_names, cursor)
    nodes.append(trigger_node)
    trigger_name = trigger_node["name"]

    test_webhook = _maybe_test_webhook(trigger_node, spec.name, used_names)
    if test_webhook is not None:
        nodes.append(test_webhook)

    action_types = {
        _action_key(action, index): action.type.lower()
        for index, action in enumerate(spec.actions)
    }
    action_id_to_name: dict[str, str] = {}
    final_nodes: list[dict[str, Any]] = []
    prep_chains: list[list[str]] = []

    for index, action in enumerate(spec.actions):
        built_nodes, final_node, prep_names = _build_action_nodes(
            action=action,
            index=index,
            used_names=used_names,
            cursor=cursor,
            id_to_node_name=action_id_to_name,
            trigger_name=trigger_name,
            action_types=action_types,
        )
        nodes.extend(built_nodes)
        final_nodes.append(final_node)
        prep_chains.append(prep_names)
        action_id_to_name[_action_key(action, index)] = final_node["name"]

    for index, action in enumerate(spec.actions):
        final_node = final_nodes[index]
        source_name = _resolve_source_name(
            action=action,
            index=index,
            trigger_name=trigger_name,
            action_id_to_name=action_id_to_name,
            final_nodes=final_nodes,
        )
        entry_name = final_node["name"]
        prep_chain = prep_chains[index]
        condition = action.config.get("condition")
        if condition:
            if_node = _build_if_node(
                action=action,
                index=index,
                used_names=used_names,
                cursor=cursor,
                id_to_node_name=action_id_to_name,
                trigger_name=trigger_name,
            )
            nodes.append(if_node)
            _add_connection(connections, source_name, if_node["name"], output_index=0)
            next_name = prep_chain[0] if prep_chain else entry_name
            _add_connection(connections, if_node["name"], next_name, output_index=0)
            _ensure_output(connections, if_node["name"], 1)
        else:
            next_name = prep_chain[0] if prep_chain else entry_name
            _add_connection(connections, source_name, next_name, output_index=0)

        for left, right in zip(prep_chain, prep_chain[1:]):
            _add_connection(connections, left, right)
        if prep_chain:
            _add_connection(connections, prep_chain[-1], entry_name)

    if test_webhook is not None and trigger_name in connections:
        connections[test_webhook["name"]] = copy.deepcopy(connections[trigger_name])

    settings: dict[str, Any] = {"executionOrder": "v1"}
    timezone = spec.trigger.config.get("timezone")
    if isinstance(timezone, str) and timezone.strip():
        settings["timezone"] = timezone.strip()

    return {
        "name": spec.name,
        "nodes": nodes,
        "connections": connections,
        "active": False,
        "settings": settings,
        "meta": {
            "description": spec.description,
            "raw_instruction": spec.raw_instruction,
            "templateCredsSetupCompleted": False,
        },
        "pinData": {},
        "versionId": str(uuid.uuid4()),
    }


def _build_action_nodes(
    action: ActionSpec,
    index: int,
    used_names: set[str],
    cursor: dict[str, int],
    id_to_node_name: dict[str, str],
    trigger_name: str,
    action_types: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    action_type = action.type.lower()
    action_key = _action_key(action, index)
    if action_type == "http_request":
        node = _build_http_node(
            action, action_key, used_names, cursor, id_to_node_name, trigger_name
        )
        return [node], node, []
    if action_type == "send_email":
        node = _build_email_node(
            action,
            action_key,
            used_names,
            cursor,
            id_to_node_name,
            trigger_name,
            action_types,
        )
        return [node], node, []
    if action_type == "generate_document":
        return _build_document_nodes(
            action, action_key, used_names, cursor, id_to_node_name, trigger_name
        )
    if action_type == "database_insert":
        return _build_database_nodes(
            action, action_key, used_names, cursor, id_to_node_name, trigger_name
        )
    node = _build_code_placeholder_node(action, action_key, used_names, cursor)
    return [node], node, []


def _build_trigger_node(
    trigger: TriggerSpec,
    workflow_name: str,
    used_names: set[str],
    cursor: dict[str, int],
) -> dict[str, Any]:
    trigger_type = trigger.type.lower()
    node_type = TRIGGER_NODE_TYPES.get(trigger_type, DEFAULT_TRIGGER_TYPE)
    name = _unique_node_name(f"Trigger_{trigger.type}", used_names)
    notes = None
    if trigger_type not in TRIGGER_NODE_TYPES:
        notes = (
            f"Unmapped trigger type '{trigger.type}'. "
            f"Using {DEFAULT_TRIGGER_TYPE} as a placeholder."
        )
        parameters = _webhook_parameters(trigger.config, workflow_name)
    elif node_type == "n8n-nodes-base.webhook":
        parameters = _webhook_parameters(trigger.config, workflow_name)
    elif node_type == "n8n-nodes-base.scheduleTrigger":
        parameters = _schedule_parameters(trigger.config)
    else:
        parameters = _form_parameters(trigger.config, workflow_name)

    node = _base_node(
        name=name,
        node_type=node_type,
        position=_take_position(cursor),
        parameters=parameters,
        notes=notes,
    )
    if node_type in {"n8n-nodes-base.webhook", "n8n-nodes-base.formTrigger"}:
        node["webhookId"] = str(uuid.uuid4())
    return node


def _maybe_test_webhook(
    trigger_node: dict[str, Any],
    workflow_name: str,
    used_names: set[str],
) -> dict[str, Any] | None:
    """n8n's public API can only start workflows through a webhook."""
    if trigger_node["type"] == "n8n-nodes-base.webhook":
        return None
    path = _slugify(f"workflowgpt-test-{workflow_name}")[:48] or "workflowgpt-test"
    name = _unique_node_name("Test_webhook", used_names)
    node = _base_node(
        name=name,
        node_type="n8n-nodes-base.webhook",
        position=[trigger_node["position"][0], NODE_Y + 180],
        parameters=_webhook_parameters({"path": path, "method": "POST"}, workflow_name),
        notes="Auxiliary webhook so WorkflowGPT can run this non-webhook workflow.",
    )
    node["webhookId"] = str(uuid.uuid4())
    return node


def _build_http_node(
    action: ActionSpec,
    action_key: str,
    used_names: set[str],
    cursor: dict[str, int],
    id_to_node_name: dict[str, str],
    trigger_name: str,
) -> dict[str, Any]:
    config = action.config
    method = str(config.get("method") or config.get("httpMethod") or "POST").upper()
    url = translate_value(
        str(config.get("url") or "https://example.com"),
        id_to_node_name,
        trigger_name,
    )
    parameters: dict[str, Any] = {
        "method": method,
        "url": url,
        "options": {},
    }
    headers = config.get("headers")
    if isinstance(headers, dict) and headers:
        parameters["sendHeaders"] = True
        parameters["headerParameters"] = {
            "parameters": [
                {
                    "name": str(key),
                    "value": translate_value(value, id_to_node_name, trigger_name),
                }
                for key, value in headers.items()
            ]
        }
    query = config.get("query") or config.get("qs")
    if isinstance(query, dict) and query:
        parameters["sendQuery"] = True
        parameters["queryParameters"] = {
            "parameters": [
                {
                    "name": str(key),
                    "value": translate_value(value, id_to_node_name, trigger_name),
                }
                for key, value in query.items()
            ]
        }
    if method not in {"GET", "HEAD"} and "body" in config:
        parameters["sendBody"] = True
        parameters["contentType"] = "json"
        parameters["specifyBody"] = "json"
        parameters["jsonBody"] = to_n8n_json_body(
            config.get("body"), id_to_node_name, trigger_name
        )
    timeout = config.get("timeout")
    if isinstance(timeout, (int, float)):
        parameters["options"] = {"timeout": int(timeout)}
    return _named_action_node(
        action, action_key, used_names, cursor, "n8n-nodes-base.httpRequest", parameters
    )


def _build_email_node(
    action: ActionSpec,
    action_key: str,
    used_names: set[str],
    cursor: dict[str, int],
    id_to_node_name: dict[str, str],
    trigger_name: str,
    action_types: dict[str, str],
) -> dict[str, Any]:
    config = action.config
    body = config.get("body", config.get("text", config.get("message", "")))
    html = config.get("html")
    parameters: dict[str, Any] = {
        "fromEmail": translate_value(
            str(config.get("fromEmail") or config.get("from") or "workflowgpt@localhost"),
            id_to_node_name,
            trigger_name,
        ),
        "toEmail": translate_value(
            str(config.get("toEmail") or config.get("to") or ""),
            id_to_node_name,
            trigger_name,
        ),
        "subject": translate_value(
            str(config.get("subject") or "WorkflowGPT notification"),
            id_to_node_name,
            trigger_name,
        ),
        "options": {},
    }
    if html:
        parameters["emailFormat"] = "html"
        parameters["html"] = translate_value(str(html), id_to_node_name, trigger_name)
    else:
        parameters["emailFormat"] = "text"
        parameters["text"] = translate_value(
            "" if body is None else str(body), id_to_node_name, trigger_name
        )
    depends_on = (action.depends_on or "").strip()
    if config.get("attachment") or action_types.get(depends_on) == "generate_document":
        parameters["options"]["attachments"] = "data"
    node = _named_action_node(
        action, action_key, used_names, cursor, "n8n-nodes-base.emailSend", parameters
    )
    _attach_credential(node, config, "smtp")
    return node


def _build_document_nodes(
    action: ActionSpec,
    action_key: str,
    used_names: set[str],
    cursor: dict[str, int],
    id_to_node_name: dict[str, str],
    trigger_name: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    config = action.config
    template = str(config.get("template") or "document")
    file_name = str(config.get("file_name") or config.get("fileName") or f"{template}.txt")
    data_js = expression_to_js(
        translate_value(config.get("data", "{{ trigger.body }}"), id_to_node_name, trigger_name)
    )
    js_code = "\n".join(
        [
            f"const data = {data_js};",
            f"const templateName = {json.dumps(template)};",
            "const payload = (data && typeof data === 'object') ? data : { value: data };",
            "const document = `Template: ${templateName}\\n\\n${JSON.stringify(payload, null, 2)}`;",
            f"return [{{ json: {{ ...payload, document, fileName: {json.dumps(file_name)}, template: templateName }} }}];",
        ]
    )
    render = _base_node(
        name=_unique_node_name(f"Render_{action_key}", used_names),
        node_type=CODE_NODE_TYPE,
        position=_take_position(cursor),
        parameters={"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": js_code},
    )
    convert = _named_action_node(
        action,
        action_key,
        used_names,
        cursor,
        "n8n-nodes-base.convertToFile",
        {
            "operation": "toText",
            "sourceProperty": "document",
            "options": {"fileName": "={{ $json.fileName }}"},
        },
    )
    return [render, convert], convert, [render["name"]]


def _build_database_nodes(
    action: ActionSpec,
    action_key: str,
    used_names: set[str],
    cursor: dict[str, int],
    id_to_node_name: dict[str, str],
    trigger_name: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    config = action.config
    record = config.get("record", "{{ trigger.body }}")
    record_js = expression_to_js(
        translate_value(record, id_to_node_name, trigger_name)
    )
    js_code = "\n".join(
        [
            f"let record = {record_js};",
            "if (typeof record === 'string') {",
            "  try { record = JSON.parse(record); } catch (error) {}",
            "}",
            "if (record === null || typeof record !== 'object' || Array.isArray(record)) {",
            "  record = { value: record };",
            "}",
            "return [{ json: record }];",
        ]
    )
    shape = _base_node(
        name=_unique_node_name(f"Shape_{action_key}", used_names),
        node_type=CODE_NODE_TYPE,
        position=_take_position(cursor),
        parameters={"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": js_code},
    )
    engine = str(config.get("engine") or "postgres").lower()
    table = str(config.get("table") or config.get("table_name") or "records")
    schema = str(config.get("schema") or "public")
    if engine == "supabase":
        node_type = "n8n-nodes-base.supabase"
        parameters = {
            "resource": "row",
            "operation": "create",
            "tableId": table,
            "dataToSend": "autoMapInputData",
        }
        credential_type = "supabaseApi"
    elif engine in {"mysql", "mariadb"}:
        node_type = "n8n-nodes-base.mySql"
        parameters = {
            "operation": "insert",
            "table": table,
            "dataMode": "autoMapInputData",
            "options": {},
        }
        credential_type = "mySql"
    else:
        node_type = "n8n-nodes-base.postgres"
        parameters = {
            "operation": "insert",
            "schema": {
                "__rl": True,
                "mode": "list",
                "value": schema,
                "cachedResultName": schema,
            },
            "table": {
                "__rl": True,
                "mode": "list",
                "value": table,
                "cachedResultName": table,
            },
            "columns": {
                "mappingMode": "autoMapInputData",
                "value": {},
                "matchingColumns": [],
                "schema": [],
            },
            "options": {},
        }
        credential_type = "postgres"
    insert = _named_action_node(
        action, action_key, used_names, cursor, node_type, parameters
    )
    _attach_credential(insert, config, credential_type)
    return [shape, insert], insert, [shape["name"]]


def _build_if_node(
    action: ActionSpec,
    index: int,
    used_names: set[str],
    cursor: dict[str, int],
    id_to_node_name: dict[str, str],
    trigger_name: str,
) -> dict[str, Any]:
    action_key = _action_key(action, index)
    condition = parse_condition(
        action.config.get("condition"), id_to_node_name, trigger_name
    )
    condition["id"] = str(uuid.uuid4())
    return _base_node(
        name=_unique_node_name(f"If_{action_key}", used_names),
        node_type="n8n-nodes-base.if",
        position=_take_position(cursor, y=NODE_Y - 140),
        parameters={
            "conditions": {
                "options": {
                    "caseSensitive": False,
                    "leftValue": "",
                    "typeValidation": "loose",
                    "version": 2,
                },
                "conditions": [condition],
                "combinator": "and",
            },
            "options": {},
        },
    )


def _build_code_placeholder_node(
    action: ActionSpec,
    action_key: str,
    used_names: set[str],
    cursor: dict[str, int],
) -> dict[str, Any]:
    config = {
        key: value for key, value in action.config.items() if key != "id"
    }
    js_code = "\n".join(
        [
            f"const config = {json.dumps(config)};",
            "const incoming = $input.first()?.json ?? {};",
            "return [{ json: { ...incoming, workflowgpt_action: config } }];",
        ]
    )
    node = _named_action_node(
        action, action_key, used_names, cursor, CODE_NODE_TYPE, {
            "mode": "runOnceForAllItems",
            "language": "javaScript",
            "jsCode": js_code,
        }
    )
    node["notes"] = (
        f"No built-in n8n node is mapped for action type '{action.type}'. "
        "The Code node forwards the incoming item plus the original config."
    )
    node["notesInFlow"] = True
    return node


def _named_action_node(
    action: ActionSpec,
    action_key: str,
    used_names: set[str],
    cursor: dict[str, int],
    node_type: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    display = action.config.get("id") or action.type
    name = _unique_node_name(str(display), used_names)
    notes = None
    if action.config.get("condition"):
        notes = f"condition: {action.config['condition']}"
    return _base_node(
        name=name,
        node_type=node_type,
        position=_take_position(cursor),
        parameters=parameters,
        notes=notes,
    )


def _base_node(
    name: str,
    node_type: str,
    position: list[int],
    parameters: dict[str, Any],
    notes: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": name,
        "type": node_type,
        "typeVersion": TYPE_VERSIONS.get(node_type, 1),
        "position": position,
        "parameters": parameters,
    }
    if notes:
        node["notes"] = notes
        node["notesInFlow"] = True
    return node


def _webhook_parameters(config: dict[str, Any], workflow_name: str) -> dict[str, Any]:
    method = str(config.get("httpMethod") or config.get("method") or "POST").upper()
    raw_path = str(config.get("path") or _slugify(workflow_name) or "workflow")
    path = raw_path.strip().strip("/") or "workflow"
    return {
        "httpMethod": method,
        "path": path,
        "responseMode": "onReceived",
        "options": {},
    }


def _schedule_parameters(config: dict[str, Any]) -> dict[str, Any]:
    cron = config.get("cron") or config.get("expression")
    if isinstance(cron, str) and cron.strip():
        interval = {"field": "cronExpression", "expression": cron.strip()}
    else:
        interval = {
            "field": "days",
            "daysInterval": int(config.get("daysInterval") or 1),
            "triggerAtHour": int(config.get("hour") or config.get("triggerAtHour") or 9),
            "triggerAtMinute": int(config.get("minute") or config.get("triggerAtMinute") or 0),
        }
    return {"rule": {"interval": [interval]}}


def _form_parameters(config: dict[str, Any], workflow_name: str) -> dict[str, Any]:
    title = str(config.get("formTitle") or config.get("form_id") or config.get("title") or workflow_name)
    raw_fields = config.get("fields") or config.get("formFields")
    values: list[dict[str, Any]] = []
    if isinstance(raw_fields, list):
        for field in raw_fields:
            if isinstance(field, str):
                values.append(
                    {"fieldLabel": field, "fieldType": "text", "requiredField": False}
                )
            elif isinstance(field, dict):
                label = field.get("fieldLabel") or field.get("name") or field.get("label")
                if label:
                    values.append(
                        {
                            "fieldLabel": str(label),
                            "fieldType": str(field.get("fieldType") or field.get("type") or "text"),
                            "requiredField": bool(field.get("requiredField") or field.get("required") or False),
                        }
                    )
    if not values:
        values.append({"fieldLabel": "payload", "fieldType": "textarea", "requiredField": False})
    path = str(config.get("path") or _slugify(title) or "form").strip().strip("/")
    return {
        "formTitle": title,
        "path": path,
        "formFields": {"values": values},
        "options": {},
    }


def _attach_credential(node: dict[str, Any], config: dict[str, Any], credential_type: str) -> None:
    credential_id = config.get("credential_id") or config.get("credentialId")
    if not credential_id:
        return
    node["credentials"] = {
        credential_type: {
            "id": str(credential_id),
            "name": str(config.get("credential_name") or config.get("credentialName") or credential_type),
        }
    }


def _resolve_source_name(
    action: ActionSpec,
    index: int,
    trigger_name: str,
    action_id_to_name: dict[str, str],
    final_nodes: list[dict[str, Any]],
) -> str:
    depends_on = (action.depends_on or "").strip()
    if depends_on and depends_on in action_id_to_name:
        return action_id_to_name[depends_on]
    if index > 0:
        return final_nodes[index - 1]["name"]
    return trigger_name


def _add_connection(
    connections: dict[str, Any],
    source_name: str,
    target_name: str,
    output_index: int = 0,
) -> None:
    source = connections.setdefault(source_name, {"main": []})
    main_outputs: list[list[dict[str, Any]]] = source.setdefault("main", [])
    while len(main_outputs) <= output_index:
        main_outputs.append([])
    main_outputs[output_index].append(
        {"node": target_name, "type": "main", "index": 0}
    )


def _ensure_output(connections: dict[str, Any], source_name: str, output_index: int) -> None:
    source = connections.setdefault(source_name, {"main": []})
    main_outputs: list[list[dict[str, Any]]] = source.setdefault("main", [])
    while len(main_outputs) <= output_index:
        main_outputs.append([])


def _take_position(cursor: dict[str, int], y: int = NODE_Y) -> list[int]:
    position = [cursor["x"], y]
    cursor["x"] += NODE_X_GAP
    return position


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

from __future__ import annotations

import json
import re
from typing import Any

_TEMPLATE_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_CONDITION_RE = re.compile(
    r"^(?P<left>.+?)\s+(?P<op>is not|is|not equals|equals|eq|contains|!=|==)\s+(?P<right>.+)$",
    re.IGNORECASE,
)
_ALIASES = ("body", "record", "file", "output")


def translate_value(
    value: Any,
    id_to_node_name: dict[str, str],
    trigger_node_name: str,
) -> Any:
    """Rewrite WorkflowSpec templates into n8n expression strings."""
    if isinstance(value, str):
        return translate_string(value, id_to_node_name, trigger_node_name)
    if isinstance(value, list):
        return [
            translate_value(item, id_to_node_name, trigger_node_name) for item in value
        ]
    if isinstance(value, dict):
        return {
            key: translate_value(item, id_to_node_name, trigger_node_name)
            for key, item in value.items()
        }
    return value


def translate_string(
    text: str,
    id_to_node_name: dict[str, str],
    trigger_node_name: str,
) -> str:
    if not _TEMPLATE_RE.search(text):
        return text

    def replace(match: re.Match[str]) -> str:
        expr = ref_to_n8n(match.group(1), id_to_node_name, trigger_node_name)
        return "{{ " + expr + " }}"

    replaced = _TEMPLATE_RE.sub(replace, text).strip()
    full = re.fullmatch(r"\{\{\s*(.+?)\s*\}\}", replaced)
    if full:
        return "={{ " + full.group(1).strip() + " }}"
    return "=" + replaced


def ref_to_n8n(
    reference: str,
    id_to_node_name: dict[str, str],
    trigger_node_name: str,
) -> str:
    """Turn `trigger.body.email` or `fetch_user.body` into an n8n expression."""
    inner = reference.strip()
    if inner in {"trigger", "trigger.body"}:
        return _node_json(trigger_node_name)

    if inner.startswith("trigger.body."):
        return _with_path(_node_json(trigger_node_name), inner[len("trigger.body.") :])
    if inner.startswith("trigger."):
        return _with_path(_node_json(trigger_node_name), inner[len("trigger.") :])

    head, _, tail = inner.partition(".")
    node_name = id_to_node_name.get(head)
    if node_name is None:
        return f"$json.{inner}" if inner else "$json"
    return _with_path(_node_json(node_name), _strip_alias(tail))


def expression_to_js(value: Any) -> str:
    """Convert a translated value into a JavaScript expression."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("={{") and stripped.endswith("}}"):
            return stripped[3:-2].strip()
        if stripped.startswith("="):
            return json.dumps(stripped[1:])
        return json.dumps(value)
    if isinstance(value, dict):
        parts = [
            f"{json.dumps(key)}: {expression_to_js(item)}" for key, item in value.items()
        ]
        return "{ " + ", ".join(parts) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(expression_to_js(item) for item in value) + "]"
    return json.dumps(value)


def to_n8n_json_body(
    body: Any,
    id_to_node_name: dict[str, str],
    trigger_node_name: str,
) -> str:
    translated = translate_value(body, id_to_node_name, trigger_node_name)
    if isinstance(translated, str) and translated.startswith("={{") and translated.endswith("}}"):
        return translated
    return "={{ " + expression_to_js(translated) + " }}"


def parse_condition(
    condition: Any,
    id_to_node_name: dict[str, str],
    trigger_node_name: str,
) -> dict[str, Any]:
    """Turn a spec condition into one n8n IF condition."""
    if isinstance(condition, dict):
        left = condition.get("left") or condition.get("value") or "$json"
        right = condition.get("right", condition.get("value", ""))
        op = str(condition.get("op") or condition.get("operation") or "contains")
        left_expr = (
            left
            if isinstance(left, str) and left.startswith("={{")
            else "={{ " + ref_to_n8n(str(left), id_to_node_name, trigger_node_name) + " }}"
        )
        return _if_condition(left_expr, right, _normalize_op(op))

    text = str(condition or "").strip()
    match = _CONDITION_RE.match(text)
    if not match:
        return _if_condition(
            "={{ JSON.stringify($json) }}",
            text,
            "contains",
        )

    left = match.group("left").strip()
    op = match.group("op").lower()
    right = match.group("right").strip().strip("\"'")
    left_expr = ref_to_n8n(left, id_to_node_name, trigger_node_name)
    operation = _normalize_op(op)
    if operation in {"contains", "notContains"}:
        left_value = "={{ JSON.stringify(" + left_expr + ") }}"
    else:
        left_value = "={{ " + left_expr + " }}"
    return _if_condition(left_value, right, operation)


def _if_condition(left_value: str, right: Any, operation: str) -> dict[str, Any]:
    names = {
        "contains": "filter.operator.contains",
        "notContains": "filter.operator.notContains",
        "equals": "filter.operator.equals",
        "notEquals": "filter.operator.notEquals",
    }
    return {
        "leftValue": left_value,
        "rightValue": right,
        "operator": {
            "type": "string",
            "operation": operation,
            "name": names[operation],
        },
    }


def _normalize_op(op: str) -> str:
    cleaned = op.strip().lower()
    if cleaned in {"is not", "not equals", "!="}:
        return "notContains" if cleaned == "is not" else "notEquals"
    if cleaned in {"equals", "eq", "=="}:
        return "equals"
    if cleaned == "contains":
        return "contains"
    return "contains"


def _strip_alias(tail: str) -> str:
    cleaned = tail.strip()
    if cleaned in _ALIASES:
        return ""
    for alias in _ALIASES:
        prefix = alias + "."
        if cleaned.startswith(prefix):
            return cleaned[len(prefix) :]
    return cleaned


def _node_json(node_name: str) -> str:
    escaped = node_name.replace("\\", "\\\\").replace("'", "\\'")
    return f"$('{escaped}').item.json"


def _with_path(base: str, path: str) -> str:
    cleaned = path.strip().strip(".")
    if not cleaned:
        return base
    return f"{base}.{cleaned}"

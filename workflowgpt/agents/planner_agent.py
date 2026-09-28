from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from agents.n8n_catalog import CATALOG
from agents.n8n_sanitize import sanitize_n8n_workflow
from agents.parser_agent import _call_llm, _extract_json_object
from schemas.models import ClarificationQuestion, WorkflowSpec


class AgentPlan(BaseModel):
    mode: str
    assistant_message: str = ""
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    n8n_workflow: dict[str, Any] | None = None
    workflow_spec: dict[str, Any] | None = None
    credentials: list[dict[str, Any]] = Field(default_factory=list)


_PLAN_PROMPT = """You are WorkflowGPT, an n8n automation agent.

The user describes ANY automation. You either:
1) ASK for missing requirements (API tokens, account IDs, spreadsheet URLs, email addresses, n8n OAuth credential IDs, region, cron, etc.), or
2) BUILD a complete n8n workflow JSON once you have enough.

Rules:
- Never invent secrets, tokens, passwords, or credential IDs.
- If OAuth is required (Gmail, Google Sheets, Slack official node, LinkedIn official node), ASK the user for an existing n8n credential id from their n8n instance, or for a raw API token if HTTP Request can work.
- Prefer official n8n nodes from the catalog. If the product is not listed, use n8n-nodes-base.httpRequest against that product's API.
- Always include a trigger. If the user wants a schedule, use scheduleTrigger. For inbound events, use webhook. Also add a webhook named Test_webhook when the primary trigger is NOT a webhook, so the workflow can be started from an HTTP URL.
- Connections must use n8n format: { "SourceName": { "main": [ [ { "node": "TargetName", "type": "main", "index": 0 } ] ] } }
- Node names must be unique.
- Put expressions in n8n form: ={{ $json.field }} or ={{ $('NodeName').item.json.field }}
- Return ONLY JSON. No markdown.

n8n node catalog:
""" + CATALOG + """

Return this JSON shape:
{
  "mode": "ask" or "build",
  "assistant_message": "short message to the user",
  "questions": [ { "id": "snake_id", "prompt": "what to ask", "secret": true, "placeholder": "" } ],
  "facts": { "keys the user already provided that you should remember": "value" },
  "n8n_workflow": null or { "name": "", "nodes": [], "connections": {}, "settings": { "executionOrder": "v1" } },
  "workflow_spec": null or a WorkflowSpec object if you cannot emit n8n JSON,
  "credentials": [ { "node_name": "HTTP Request", "n8n_type": "httpHeaderAuth", "name": "Lead API", "data": { "name": "Authorization", "value": "Bearer {{facts.api_token}}" } } ]
}

When mode is ask, n8n_workflow must be null.
When mode is build, questions must be empty and n8n_workflow must have nodes.
Replace {{facts.KEY}} in credential data and node parameters with known fact values.
"""


def plan_turn(
    message: str,
    conversation: list[dict[str, str]],
    facts: dict[str, Any],
) -> AgentPlan:
    prompt = _PLAN_PROMPT + "\nKnown facts (secrets included, do not repeat them in assistant_message):\n"
    prompt += json.dumps(_redact_for_prompt(facts), indent=2) + "\n"
    prompt += "Conversation:\n"
    for item in conversation[-12:]:
        role = item.get("role") or "user"
        content = item.get("content") or ""
        prompt += f"{role}: {content}\n"
    prompt += f"user: {message}\nReturn ONLY JSON."

    raw = _call_llm(prompt, max_tokens=8192)
    try:
        payload = _extract_json_object(raw)
        plan = _coerce_plan(payload, facts)
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
        correction = (
            _PLAN_PROMPT
            + f"\nYour previous JSON was invalid ({exc}). Return ONLY corrected JSON.\n"
            + f"Previous:\n{raw}\nuser: {message}"
        )
        payload = _extract_json_object(_call_llm(correction, max_tokens=8192))
        plan = _coerce_plan(payload, facts)
    return plan


def _coerce_plan(payload: dict[str, Any], existing_facts: dict[str, Any]) -> AgentPlan:
    mode = str(payload.get("mode") or "ask").lower()
    if mode not in {"ask", "build"}:
        mode = "ask"
    questions = []
    for item in payload.get("questions") or []:
        if not isinstance(item, dict) or not item.get("id") or not item.get("prompt"):
            continue
        questions.append(
            ClarificationQuestion(
                id=str(item["id"]),
                prompt=str(item["prompt"]),
                secret=bool(item.get("secret")),
                placeholder=str(item.get("placeholder") or ""),
            )
        )
    facts = dict(existing_facts)
    incoming = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    for key, value in incoming.items():
        if value not in (None, ""):
            facts[str(key)] = value

    workflow = payload.get("n8n_workflow")
    if isinstance(workflow, dict) and workflow.get("nodes"):
        workflow = _replace_fact_placeholders(workflow, facts)
        try:
            workflow = sanitize_n8n_workflow(workflow)
        except ValueError:
            workflow = None
    else:
        workflow = None

    spec = payload.get("workflow_spec")
    if isinstance(spec, dict):
        spec = _replace_fact_placeholders(spec, facts)
        try:
            WorkflowSpec.model_validate(spec)
        except ValidationError:
            spec = None
    else:
        spec = None

    credentials = []
    for item in payload.get("credentials") or []:
        if isinstance(item, dict) and item.get("n8n_type"):
            credentials.append(_replace_fact_placeholders(item, facts))

    if mode == "build" and workflow is None and spec is None:
        mode = "ask"
        if not questions:
            questions.append(
                ClarificationQuestion(
                    id="more_detail",
                    prompt="I still need a bit more detail to build this in n8n. Which app, trigger, and action should the automation use?",
                )
            )

    if mode == "ask" and not questions:
        questions.append(
            ClarificationQuestion(
                id="more_detail",
                prompt="What should trigger this automation, and what should it do? Include any API keys, URLs, or account IDs you already have.",
            )
        )

    if mode == "build":
        questions = []

    return AgentPlan(
        mode=mode,
        assistant_message=str(payload.get("assistant_message") or ""),
        questions=questions,
        facts=facts,
        n8n_workflow=workflow,
        workflow_spec=spec,
        credentials=credentials,
    )


def _replace_fact_placeholders(value: Any, facts: dict[str, Any]) -> Any:
    if isinstance(value, str):
        text = value
        for key, fact in facts.items():
            text = text.replace("{{facts." + str(key) + "}}", str(fact))
        return text
    if isinstance(value, list):
        return [_replace_fact_placeholders(item, facts) for item in value]
    if isinstance(value, dict):
        return {key: _replace_fact_placeholders(item, facts) for key, item in value.items()}
    return value


def _redact_for_prompt(facts: dict[str, Any]) -> dict[str, Any]:
    """Keep values so the model can fill nodes, but mark secret-looking keys."""
    return dict(facts)

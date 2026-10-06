from __future__ import annotations

import json
import re
import time
from typing import Any

from pydantic import ValidationError

import httpx
from anthropic import Anthropic

from config import GEMINI_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_PROVIDER, OPENAI_BASE_URL
from schemas.models import WorkflowSpec

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)

_SYSTEM_PROMPT = """You convert a natural-language workflow instruction into a WorkflowSpec JSON object.

Return ONLY valid JSON. No markdown, no commentary, no code fences.

The JSON must match this schema:
- name (string): short workflow name
- description (string): one-sentence summary
- trigger: { "type": string, "config": object }
  Trigger types include: "webhook", "schedule", "form_submission"
- actions: list of { "type": string, "config": object, "depends_on": string or null }
  Action types include: "http_request", "send_email", "generate_document", "database_insert"
  Put a unique "id" in each action's config. Use depends_on to reference that id when an action must wait for another.
  For conditionals, give sibling actions the same depends_on and set config.condition to the branch predicate.
- raw_instruction (string): copy the user's instruction exactly

JSON schema:
""" + json.dumps(WorkflowSpec.model_json_schema(), indent=2) + """

Few-shot examples:

Example 1 — simple webhook, single action
Instruction: When a webhook is received, POST the payload to https://api.example.com/ingest.
JSON:
{
  "name": "Webhook ingest",
  "description": "Forward incoming webhook payloads to an HTTP endpoint.",
  "trigger": {
    "type": "webhook",
    "config": { "method": "POST", "path": "/webhook" }
  },
  "actions": [
    {
      "type": "http_request",
      "config": {
        "id": "forward_payload",
        "method": "POST",
        "url": "https://api.example.com/ingest",
        "body": "{{ trigger.body }}"
      },
      "depends_on": null
    }
  ],
  "raw_instruction": "When a webhook is received, POST the payload to https://api.example.com/ingest."
}

Example 2 — multi-step chain (do A then B then C)
Instruction: When a form is submitted, save the row in the database, then generate a PDF contract, then email it to the submitter.
JSON:
{
  "name": "Form to signed contract",
  "description": "Persist a form submission, generate a contract PDF, then email it.",
  "trigger": {
    "type": "form_submission",
    "config": { "form_id": "intake" }
  },
  "actions": [
    {
      "type": "database_insert",
      "config": {
        "id": "save_submission",
        "table": "submissions",
        "record": "{{ trigger.body }}"
      },
      "depends_on": null
    },
    {
      "type": "generate_document",
      "config": {
        "id": "make_contract",
        "template": "contract_pdf",
        "data": "{{ save_submission.record }}"
      },
      "depends_on": "save_submission"
    },
    {
      "type": "send_email",
      "config": {
        "id": "email_contract",
        "to": "{{ trigger.body.email }}",
        "subject": "Your contract",
        "attachment": "{{ make_contract.file }}"
      },
      "depends_on": "make_contract"
    }
  ],
  "raw_instruction": "When a form is submitted, save the row in the database, then generate a PDF contract, then email it to the submitter."
}

Example 3 — conditional (if X then A else B)
Instruction: Every weekday at 9am, check https://status.example.com/health. If it is unhealthy, send an email to ops@example.com; otherwise insert a healthy row into the uptime table.
JSON:
{
  "name": "Weekday health check",
  "description": "Poll a health endpoint on a schedule and email or log based on the result.",
  "trigger": {
    "type": "schedule",
    "config": { "cron": "0 9 * * 1-5", "timezone": "UTC" }
  },
  "actions": [
    {
      "type": "http_request",
      "config": {
        "id": "check_health",
        "method": "GET",
        "url": "https://status.example.com/health"
      },
      "depends_on": null
    },
    {
      "type": "send_email",
      "config": {
        "id": "alert_ops",
        "to": "ops@example.com",
        "subject": "Service unhealthy",
        "body": "{{ check_health.body }}",
        "condition": "check_health is unhealthy"
      },
      "depends_on": "check_health"
    },
    {
      "type": "database_insert",
      "config": {
        "id": "log_healthy",
        "table": "uptime",
        "record": { "status": "healthy" },
        "condition": "check_health is healthy"
      },
      "depends_on": "check_health"
    }
  ],
  "raw_instruction": "Every weekday at 9am, check https://status.example.com/health. If it is unhealthy, send an email to ops@example.com; otherwise insert a healthy row into the uptime table."
}

Example 4 — webhook with two dependent HTTP steps
Instruction: On webhook, fetch the user from https://api.example.com/users/{{id}} then POST that user to https://crm.example.com/contacts.
JSON:
{
  "name": "Webhook user sync",
  "description": "Look up a user from a webhook id and upsert them in the CRM.",
  "trigger": {
    "type": "webhook",
    "config": { "method": "POST", "path": "/sync-user" }
  },
  "actions": [
    {
      "type": "http_request",
      "config": {
        "id": "fetch_user",
        "method": "GET",
        "url": "https://api.example.com/users/{{ trigger.body.id }}"
      },
      "depends_on": null
    },
    {
      "type": "http_request",
      "config": {
        "id": "upsert_crm",
        "method": "POST",
        "url": "https://crm.example.com/contacts",
        "body": "{{ fetch_user.body }}"
      },
      "depends_on": "fetch_user"
    }
  ],
  "raw_instruction": "On webhook, fetch the user from https://api.example.com/users/{{id}} then POST that user to https://crm.example.com/contacts."
}
"""


def parse_instruction(raw_instruction: str) -> WorkflowSpec:
    """Turn a natural-language instruction into a validated WorkflowSpec."""
    user_prompt = _build_user_prompt(raw_instruction)
    raw_response = _call_llm(user_prompt)
    try:
        return _parse_and_validate(raw_response, raw_instruction)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        correction_prompt = _build_correction_prompt(
            raw_instruction, raw_response, exc
        )
        retry_response = _call_llm(correction_prompt)
        return _parse_and_validate(retry_response, raw_instruction)


def _build_user_prompt(raw_instruction: str) -> str:
    return (
        f"{_SYSTEM_PROMPT}\n"
        f"Now convert this instruction. Return ONLY JSON.\n"
        f"Instruction: {raw_instruction}"
    )


def _build_correction_prompt(
    raw_instruction: str,
    previous_response: str,
    error: Exception,
) -> str:
    return (
        f"{_SYSTEM_PROMPT}\n"
        "Your previous JSON was invalid. Return ONLY corrected JSON matching WorkflowSpec.\n"
        f"Validation error: {error}\n"
        f"Previous response:\n{previous_response}\n"
        f"Instruction: {raw_instruction}"
    )


def _parse_and_validate(raw_response: str, raw_instruction: str) -> WorkflowSpec:
    payload = _extract_json_object(raw_response)
    spec = WorkflowSpec.model_validate(payload)
    return spec.model_copy(update={"raw_instruction": raw_instruction})


def _extract_json_object(raw_response: str) -> dict[str, Any]:
    text = raw_response.strip()
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM response JSON must be an object matching WorkflowSpec")
    return payload


def _call_llm(prompt: str, max_tokens: int = 4096) -> str:
    """Call the configured LLM and return the assistant text (JSON-only prompt)."""
    provider = (LLM_PROVIDER or "anthropic").strip().lower()
    api_key = (LLM_API_KEY or "").strip()
    if not api_key:
        raise ValueError("LLM_API_KEY is required")
    if provider == "anthropic":
        return _call_anthropic(prompt, api_key, max_tokens=max_tokens)
    if provider == "openai":
        return _call_openai(prompt, api_key, max_tokens=max_tokens)
    if provider == "gemini":
        return _call_gemini(prompt, api_key, max_tokens=max_tokens)
    raise ValueError(
        f"Unsupported LLM_PROVIDER={LLM_PROVIDER!r}. Use 'anthropic', 'openai', or 'gemini'."
    )


def _call_anthropic(prompt: str, api_key: str, max_tokens: int = 4096) -> str:
    client = Anthropic(api_key=api_key)
    message = client.messages.create(
        model=(LLM_MODEL or "claude-sonnet-4-5").strip(),
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [
        block.text
        for block in message.content
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ]
    text = "".join(parts).strip()
    if not text:
        raise ValueError("Anthropic returned an empty response")
    return text


def _call_openai(prompt: str, api_key: str, max_tokens: int = 4096) -> str:
    model = (LLM_MODEL or "").strip()
    if not model or model.startswith("claude"):
        model = "gpt-4o-mini"
    base = (OPENAI_BASE_URL or "https://api.openai.com/v1").strip().rstrip("/")
    try:
        response = httpx.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise ValueError(f"OpenAI request failed: {exc}") from exc
    if response.is_error:
        raise ValueError(
            f"OpenAI request failed with status {response.status_code}: {response.text}"
        )
    payload = response.json()
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise ValueError("OpenAI returned no choices")
    message = choices[0].get("message") or {}
    text = str(message.get("content") or "").strip()
    if not text:
        raise ValueError("OpenAI returned an empty response")
    return text


def _call_gemini(prompt: str, api_key: str, max_tokens: int = 4096) -> str:
    model = (LLM_MODEL or "").strip()
    if not model or model.startswith("claude") or model.startswith("gpt-"):
        model = "gemini-3.8-flash"
    base = (GEMINI_BASE_URL or "https://generativelanguage.googleapis.com/v1beta").strip().rstrip("/")
    url = f"{base}/models/{model}:generateContent"
    last_error = "Gemini request failed"
    for attempt in range(4):
        try:
            response = httpx.post(
                url,
                headers={
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens},
                },
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            last_error = f"Gemini request failed: {exc}"
            time.sleep(2 ** attempt)
            continue
        if getattr(response, "status_code", 0) in {429, 503}:
            last_error = (
                f"Gemini is busy (status {response.status_code}). "
                "Wait about a minute and send the same message again."
            )
            time.sleep(2 ** attempt)
            continue
        if response.is_error:
            raise ValueError(
                f"Gemini request failed with status {response.status_code}: {response.text}"
            )
        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates or not isinstance(candidates[0], dict):
            raise ValueError("Gemini returned no candidates")
        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        text = "".join(
            str(part.get("text") or "") for part in parts if isinstance(part, dict)
        ).strip()
        if not text:
            raise ValueError("Gemini returned an empty response")
        return text
    raise ValueError(last_error)

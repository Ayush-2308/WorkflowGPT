import json

import pytest

from agents.parser_agent import _call_llm, _extract_json_object, _parse_and_validate


def test_extracts_json_from_fenced_and_wrapped_text():
    fenced = '```json\n{"name": "A"}\n```'
    assert _extract_json_object(fenced) == {"name": "A"}
    wrapped = 'Sure: {"name": "B", "ok": true} thanks'
    assert _extract_json_object(wrapped)["name"] == "B"


def test_parse_overwrites_raw_instruction():
    payload = {
        "name": "Webhook ingest",
        "description": "Forward a webhook.",
        "trigger": {"type": "webhook", "config": {}},
        "actions": [],
        "raw_instruction": "ignored",
    }
    spec = _parse_and_validate(json.dumps(payload), "actual instruction")
    assert spec.raw_instruction == "actual instruction"


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setattr("agents.parser_agent.LLM_PROVIDER", "cohere")
    monkeypatch.setattr("agents.parser_agent.LLM_API_KEY", "test-key")
    with pytest.raises(ValueError, match="anthropic"):
        _call_llm("return json")


def test_openai_call_reads_message_content(monkeypatch):
    monkeypatch.setattr("agents.parser_agent.LLM_PROVIDER", "openai")
    monkeypatch.setattr("agents.parser_agent.LLM_API_KEY", "test-key")
    monkeypatch.setattr("agents.parser_agent.LLM_MODEL", "claude-sonnet-4-5")

    seen: dict = {}

    class Response:
        is_error = False

        def json(self):
            return {"choices": [{"message": {"content": "{\"name\": \"ok\"}"}}]}

    def fake_post(*args, **kwargs):
        seen.update(kwargs)
        return Response()

    monkeypatch.setattr("agents.parser_agent.httpx.post", fake_post)
    assert _call_llm("prompt") == '{"name": "ok"}'
    assert seen["json"]["model"] == "gpt-4o-mini"


def test_gemini_call_reads_candidate_text(monkeypatch):
    monkeypatch.setattr("agents.parser_agent.LLM_PROVIDER", "gemini")
    monkeypatch.setattr("agents.parser_agent.LLM_API_KEY", "test-key")
    monkeypatch.setattr("agents.parser_agent.LLM_MODEL", "claude-sonnet-4-5")

    seen: dict = {}

    class Response:
        is_error = False

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "{\"name\": \"ok\"}"}]}}]}

    def fake_post(*args, **kwargs):
        seen["url"] = args[0] if args else kwargs.get("url")
        seen["header"] = kwargs["headers"]["x-goog-api-key"]
        return Response()

    monkeypatch.setattr("agents.parser_agent.httpx.post", fake_post)
    assert _call_llm("prompt") == '{"name": "ok"}'
    assert seen["url"].endswith("/models/gemini-3.8-flash:generateContent")
    assert seen["header"] == "test-key"

import pytest

from agents.executor_agent import (
    N8nExecutorError,
    _extract_form_target,
    _extract_trigger_target,
    _extract_webhook_target,
    _pick_recent_execution,
)


def test_prefers_auxiliary_test_webhook():
    workflow = {
        "nodes": [
            {
                "name": "Trigger_schedule",
                "type": "n8n-nodes-base.scheduleTrigger",
                "parameters": {},
            },
            {
                "name": "Test_webhook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "workflowgpt-test", "httpMethod": "POST"},
            },
        ]
    }
    assert _extract_webhook_target(workflow) == ("workflowgpt-test", "POST")
    path, method, mode = _extract_trigger_target(workflow)
    assert (path, method, mode) == ("workflowgpt-test", "POST", "json")


def test_form_trigger_is_used_when_no_webhook_exists():
    workflow = {
        "nodes": [
            {
                "name": "Form",
                "type": "n8n-nodes-base.formTrigger",
                "parameters": {"path": "intake"},
            }
        ]
    }
    assert _extract_form_target(workflow) == ("intake", "POST")
    assert _extract_trigger_target(workflow)[2] == "form"


def test_missing_runnable_trigger_returns_none():
    with pytest.raises(N8nExecutorError):
        _extract_webhook_target({"id": "1", "nodes": []})
    assert _extract_trigger_target({"id": "1", "nodes": []}) is None


def test_pick_recent_execution_skips_older_runs():
    older = {"id": "old", "startedAt": "2020-01-01T00:00:00+00:00", "status": "success"}
    newer = {"id": "new", "startedAt": "2099-01-01T00:00:00+00:00", "status": "success"}
    picked = _pick_recent_execution([older, newer], triggered_at=1_700_000_000)
    assert picked["id"] == "new"

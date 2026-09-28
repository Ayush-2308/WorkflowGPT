from agents.deployer_agent import _extract_workflow_id, _workflow_create_payload
import pytest

from agents.deployer_agent import N8nDeployError


def test_create_payload_drops_editor_only_fields():
    payload = _workflow_create_payload(
        {
            "name": "Demo",
            "nodes": [],
            "connections": {},
            "settings": {"executionOrder": "v1"},
            "meta": {"description": "hidden"},
            "active": False,
        }
    )
    assert "meta" not in payload
    assert payload["name"] == "Demo"
    assert payload["settings"]["executionOrder"] == "v1"


def test_extract_workflow_id_reads_top_level_and_nested():
    assert _extract_workflow_id({"id": 15}) == "15"
    assert _extract_workflow_id({"data": {"id": "abc"}}) == "abc"
    with pytest.raises(N8nDeployError):
        _extract_workflow_id({"ok": True})

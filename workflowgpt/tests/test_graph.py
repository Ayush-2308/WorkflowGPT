from schemas.models import PipelineState
from db.supabase_client import workflow_row
from graph import resolve_persisted_status, route_after_build, route_after_deploy, route_after_parse


def _state(**kwargs) -> PipelineState:
    data = {
        "request_id": "req-1",
        "raw_instruction": "do the thing",
        "deployment_status": "pending",
    }
    data.update(kwargs)
    return PipelineState(**data)


def test_only_a_successful_test_is_marked_completed():
    assert resolve_persisted_status("tested") == "completed"
    assert resolve_persisted_status("test_failed") == "test_failed"
    assert resolve_persisted_status("parse_failed") == "parse_failed"
    assert resolve_persisted_status("deployment_failed") == "deployment_failed"


def test_failures_route_to_persist():
    assert route_after_parse(_state(deployment_status="needs_input")) == "persist"
    assert (
        route_after_parse(
            _state(
                deployment_status="built",
                n8n_workflow_json={"nodes": [{"name": "A"}]},
            )
        )
        == "deploy"
    )
    assert route_after_parse(_state(deployment_status="parsed", workflow_spec={"name": "x"})) == "build"
    assert route_after_build(_state(deployment_status="build_failed")) == "persist"
    assert route_after_build(_state(deployment_status="built", n8n_workflow_json={"nodes": []})) == "deploy"
    assert route_after_deploy(_state(deployment_status="deployment_failed")) == "persist"
    assert route_after_deploy(_state(deployment_status="deploy_skipped")) == "persist"
    assert route_after_deploy(_state(deployment_status="deployed", n8n_workflow_id="42")) == "test"


def test_workflow_row_keeps_json_and_errors():
    row = workflow_row(
        _state(
            deployment_status="test_failed",
            n8n_workflow_json={"name": "Demo"},
            n8n_workflow_id="42",
            errors=["test failed: timeout"],
        )
    )
    assert row["status"] == "test_failed"
    assert row["n8n_workflow_json"]["name"] == "Demo"
    assert row["errors"] == ["test failed: timeout"]
    assert row["n8n_workflow_id"] == "42"

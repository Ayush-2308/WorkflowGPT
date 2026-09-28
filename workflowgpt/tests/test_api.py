from fastapi.testclient import TestClient

from main import app


def test_home_page_includes_the_prompt_form():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "Send" in response.text
    assert 'id="instruction"' in response.text
    assert "/agent" in response.text


def test_health_lists_missing_setting_names(monkeypatch):
    monkeypatch.setattr("config.LLM_API_KEY", "present")
    monkeypatch.setattr("config.SUPABASE_URL", "")
    monkeypatch.setattr("config.SUPABASE_KEY", "")
    monkeypatch.setattr("config.N8N_BASE_URL", "http://localhost:5678")
    monkeypatch.setattr("config.N8N_API_KEY", "")
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "incomplete"
    assert body["missing"] == ["SUPABASE_URL", "SUPABASE_KEY", "N8N_API_KEY"]
    assert "sk-" not in response.text


def test_generate_returns_editor_url_for_a_failed_test(monkeypatch):
    from schemas.models import PipelineState

    monkeypatch.setattr("main.WORKFLOWGPT_API_KEY", "")

    def fake_run(instruction: str, request_id: str | None = None) -> PipelineState:
        return PipelineState(
            request_id=request_id or "req",
            raw_instruction=instruction,
            n8n_workflow_id="abc",
            deployment_status="test_failed",
            errors=["test failed"],
        )

    monkeypatch.setattr("main._run_from_user_input", lambda message, session_id, answers: fake_run(message, session_id))
    monkeypatch.setattr("main.N8N_BASE_URL", "http://localhost:5678")
    response = TestClient(app).post(
        "/generate-workflow",
        json={"instruction": "When a webhook is received, post it."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["deployment_status"] == "test_failed"
    assert body["n8n_workflow_url"] == "http://localhost:5678/workflow/abc"
    assert body["request_id"]


def test_api_key_protects_generate(monkeypatch):
    from schemas.models import PipelineState

    monkeypatch.setattr("main.WORKFLOWGPT_API_KEY", "secret")
    monkeypatch.setattr(
        "main._run_from_user_input",
        lambda instruction, session_id, answers: PipelineState(
            request_id="req",
            raw_instruction=instruction,
            deployment_status="parse_failed",
        ),
    )
    client = TestClient(app)
    denied = client.post("/generate-workflow", json={"instruction": "hello"})
    assert denied.status_code == 401
    allowed = client.post(
        "/generate-workflow",
        headers={"X-API-Key": "secret"},
        json={"instruction": "hello"},
    )
    assert allowed.status_code != 401

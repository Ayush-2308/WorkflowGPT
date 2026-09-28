from agents.n8n_sanitize import sanitize_n8n_workflow


def test_sanitize_fills_webhook_and_linear_connections():
    workflow = sanitize_n8n_workflow(
        {
            "name": "Lead comments",
            "nodes": [
                {"name": "Hook", "type": "n8n-nodes-base.webhook", "parameters": {"path": "leads"}},
                {
                    "name": "Post",
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"method": "POST", "url": "https://example.com"},
                },
            ],
        }
    )
    assert workflow["nodes"][0]["webhookId"]
    assert workflow["nodes"][0]["typeVersion"] == 2
    assert "Hook" in workflow["connections"]
    assert workflow["connections"]["Hook"]["main"][0][0]["node"] == "Post"


def test_sanitize_rejects_empty_nodes():
    try:
        sanitize_n8n_workflow({"name": "x", "nodes": []})
    except ValueError as exc:
        assert "node" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")

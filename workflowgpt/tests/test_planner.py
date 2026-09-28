from agents.planner_agent import _coerce_plan


def test_coerce_plan_asks_when_build_has_no_workflow():
    plan = _coerce_plan(
        {
            "mode": "build",
            "assistant_message": "Need more",
            "questions": [],
            "n8n_workflow": None,
        },
        {},
    )
    assert plan.mode == "ask"
    assert plan.questions


def test_coerce_plan_sanitizes_build_json():
    plan = _coerce_plan(
        {
            "mode": "build",
            "assistant_message": "Built",
            "questions": [{"id": "x", "prompt": "unused"}],
            "n8n_workflow": {
                "name": "Demo",
                "nodes": [
                    {"name": "Hook", "type": "n8n-nodes-base.webhook", "parameters": {}},
                ],
            },
        },
        {},
    )
    assert plan.mode == "build"
    assert plan.questions == []
    assert plan.n8n_workflow["nodes"][0]["webhookId"]

from schemas.models import ActionSpec, TriggerSpec, WorkflowSpec
from agents.builder_agent import build_n8n_workflow


def _spec(**kwargs) -> WorkflowSpec:
    data = {
        "name": "Demo",
        "description": "A demo workflow.",
        "trigger": TriggerSpec(type="webhook", config={"method": "POST", "path": "/hooks/demo"}),
        "actions": [],
        "raw_instruction": "When a webhook is received, POST the payload.",
    }
    data.update(kwargs)
    return WorkflowSpec(**data)


def _nodes_by_type(workflow: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for node in workflow["nodes"]:
        grouped.setdefault(node["type"], []).append(node)
    return grouped


def test_http_request_uses_n8n_body_shape_and_expressions():
    workflow = build_n8n_workflow(
        _spec(
            actions=[
                ActionSpec(
                    type="http_request",
                    config={
                        "id": "forward_payload",
                        "method": "POST",
                        "url": "https://httpbin.org/post",
                        "body": "{{ trigger.body }}",
                    },
                )
            ]
        )
    )
    http_nodes = _nodes_by_type(workflow)["n8n-nodes-base.httpRequest"]
    assert len(http_nodes) == 1
    params = http_nodes[0]["parameters"]
    assert params["method"] == "POST"
    assert params["sendBody"] is True
    assert params["specifyBody"] == "json"
    assert params["jsonBody"] == "={{ $('Trigger_webhook').item.json }}"
    webhook = _nodes_by_type(workflow)["n8n-nodes-base.webhook"][0]
    assert webhook["typeVersion"] == 2
    assert webhook["parameters"]["path"] == "hooks/demo"
    assert "Test_webhook" not in {node["name"] for node in workflow["nodes"]}


def test_condition_becomes_if_node_with_two_outputs():
    workflow = build_n8n_workflow(
        _spec(
            trigger=TriggerSpec(type="schedule", config={"cron": "0 9 * * 1-5", "timezone": "UTC"}),
            actions=[
                ActionSpec(
                    type="http_request",
                    config={"id": "check_health", "method": "GET", "url": "https://status.example.com/health"},
                ),
                ActionSpec(
                    type="send_email",
                    config={
                        "id": "alert_ops",
                        "to": "ops@example.com",
                        "subject": "Service unhealthy",
                        "condition": "check_health is unhealthy",
                    },
                    depends_on="check_health",
                ),
            ],
        )
    )
    names = {node["name"]: node for node in workflow["nodes"]}
    assert "n8n-nodes-base.scheduleTrigger" in {node["type"] for node in workflow["nodes"]}
    assert names["Test_webhook"]["type"] == "n8n-nodes-base.webhook"
    if_node = next(node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.if")
    true_targets = [item["node"] for item in workflow["connections"][if_node["name"]]["main"][0]]
    assert true_targets == ["alert_ops"]
    assert workflow["connections"][if_node["name"]]["main"][1] == []
    assert workflow["settings"]["timezone"] == "UTC"
    email = names["alert_ops"]["parameters"]
    assert email["toEmail"] == "ops@example.com"
    assert email["fromEmail"] == "workflowgpt@localhost"
    assert "Test_webhook" in workflow["connections"]


def test_document_and_database_actions_are_real_nodes():
    workflow = build_n8n_workflow(
        _spec(
            trigger=TriggerSpec(type="form_submission", config={"form_id": "intake", "fields": ["email"]}),
            actions=[
                ActionSpec(
                    type="database_insert",
                    config={"id": "save_submission", "table": "submissions", "record": "{{ trigger.body }}"},
                ),
                ActionSpec(
                    type="generate_document",
                    config={"id": "make_contract", "template": "contract_pdf", "data": "{{ save_submission.record }}"},
                    depends_on="save_submission",
                ),
                ActionSpec(
                    type="send_email",
                    config={"id": "email_contract", "to": "{{ trigger.body.email }}", "subject": "Your contract"},
                    depends_on="make_contract",
                ),
            ],
        )
    )
    types = {node["type"] for node in workflow["nodes"]}
    assert "n8n-nodes-base.postgres" in types
    assert "n8n-nodes-base.convertToFile" in types
    assert "n8n-nodes-base.formTrigger" in types
    email = next(node for node in workflow["nodes"] if node["name"] == "email_contract")
    assert email["parameters"]["toEmail"] == "={{ $('Trigger_form_submission').item.json.email }}"
    assert email["parameters"]["options"]["attachments"] == "data"
    postgres = next(node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.postgres")
    assert postgres["parameters"]["table"]["value"] == "submissions"


def test_mysql_engine_and_credential_are_attached():
    workflow = build_n8n_workflow(
        _spec(
            actions=[
                ActionSpec(
                    type="database_insert",
                    config={
                        "id": "save_submission",
                        "engine": "mysql",
                        "table": "submissions",
                        "credential_id": "cred-1",
                        "credential_name": "App MySQL",
                    },
                )
            ]
        )
    )
    node = next(node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.mySql")
    assert node["credentials"]["mySql"]["id"] == "cred-1"
    assert node["parameters"]["table"] == "submissions"

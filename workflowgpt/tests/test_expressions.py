from agents.expressions import parse_condition, translate_string


def test_trigger_and_step_templates_become_n8n_expressions():
    names = {"fetch_user": "fetch_user", "save_submission": "save_submission"}
    assert (
        translate_string("{{ trigger.body.email }}", names, "Trigger_webhook")
        == "={{ $('Trigger_webhook').item.json.email }}"
    )
    assert (
        translate_string("{{ fetch_user.body }}", names, "Trigger_webhook")
        == "={{ $('fetch_user').item.json }}"
    )
    assert (
        translate_string("Hello {{ trigger.body.email }}", names, "Trigger_webhook")
        == "=Hello {{ $('Trigger_webhook').item.json.email }}"
    )


def test_is_condition_uses_contains_on_the_referenced_node():
    condition = parse_condition(
        "check_health is unhealthy",
        {"check_health": "check_health"},
        "Trigger_schedule",
    )
    assert condition["operator"]["operation"] == "contains"
    assert condition["rightValue"] == "unhealthy"
    assert "check_health" in condition["leftValue"]

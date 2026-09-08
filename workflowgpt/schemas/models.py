from typing import Any, Optional

from pydantic import BaseModel, Field


class TriggerSpec(BaseModel):
    type: str = Field(
        ...,
        description='Trigger type, e.g. "webhook", "schedule", "form_submission".',
    )
    config: dict[str, Any] = Field(default_factory=dict)


class ActionSpec(BaseModel):
    type: str = Field(
        ...,
        description=(
            'Action type, e.g. "http_request", "send_email", '
            '"generate_document", "database_insert".'
        ),
    )
    config: dict[str, Any] = Field(default_factory=dict)
    depends_on: Optional[str] = None


class WorkflowSpec(BaseModel):
    name: str
    description: str
    trigger: TriggerSpec
    actions: list[ActionSpec] = Field(default_factory=list)
    raw_instruction: str


class PipelineState(BaseModel):
    request_id: str
    raw_instruction: str
    workflow_spec: Optional[dict[str, Any]] = None
    n8n_workflow_json: Optional[dict[str, Any]] = None
    n8n_workflow_id: Optional[str] = None
    deployment_status: str
    test_result: Optional[dict[str, Any]] = None
    errors: list[str] = Field(default_factory=list)

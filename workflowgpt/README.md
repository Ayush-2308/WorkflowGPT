# WorkflowGPT

Turn natural-language instructions into a structured workflow spec, then into a real deployed n8n automation.

## Overview

WorkflowGPT is an n8n agent: you describe any automation in chat. If tokens, IDs, or account details are missing, it asks. Then it generates n8n workflow JSON, deploys it, and returns an editor link.

Open `http://127.0.0.1:8000` and talk to the agent (`POST /agent`). `POST /generate-workflow` is the same pipeline for a single instruction plus optional `answers`.

## Architecture

Agents are orchestrated by a LangGraph `StateGraph` (`graph.py`) whose state is `PipelineState`.

| Agent | Module | Role |
| --- | --- | --- |
| Planner | `agents/planner_agent.py` | Chat turn → ask questions or n8n workflow JSON |
| Parser | `agents/parser_agent.py` | Fallback WorkflowSpec JSON |
| Builder | `agents/builder_agent.py` | `WorkflowSpec` → n8n export JSON |
| Deployer | `agents/deployer_agent.py` | `POST /api/v1/workflows` + activate, and delete |
| Executor | `agents/executor_agent.py` | Hit the webhook or form, poll `/api/v1/executions` |
| Storage | `db/supabase_client.py` | Persist workflow JSON, status, errors, and execution logs |

Graph flow: `parse → build → deploy → test → persist`. Parse, build, and deploy failures skip ahead to `persist` so the run is still stored.

- After **parse**: if schema validation fails twice → `parse_failed`
- After **build**: if mapping throws → `build_failed`
- After **deploy**: if n8n create/activate fails → `deployment_failed`
- After **test**: success becomes `completed`; a failed run stays `test_failed`

Mapped n8n nodes:

| Spec | n8n node |
| --- | --- |
| `webhook` | Webhook |
| `schedule` | Schedule Trigger, plus a test webhook |
| `form_submission` | Form Trigger, plus a test webhook |
| `http_request` | HTTP Request |
| `send_email` | Send Email (SMTP credential attached when `credential_id` is set) |
| `generate_document` | Code node that renders text, then Convert to File |
| `database_insert` | Code node that shapes the row, then Postgres, MySQL, or Supabase |
| `condition` | IF node; the true output runs the action |

`{{ trigger.body.email }}` and `{{ step_id.body }}` are rewritten to n8n expressions. Schedule and form workflows get an extra webhook named `Test_webhook` because the n8n public API can start a workflow only through a webhook or form URL.

## Setup

From the `workflowgpt` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Fill `.env`:

```
SUPABASE_URL=
SUPABASE_KEY=
LLM_API_KEY=
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-5
OPENAI_BASE_URL=https://api.openai.com/v1
N8N_BASE_URL=http://localhost:5678
N8N_API_KEY=
WORKFLOWGPT_API_KEY=
```

`LLM_PROVIDER` is `anthropic`, `openai`, or `gemini`. For OpenAI, set `LLM_MODEL` to an OpenAI model such as `gpt-4o-mini`. For Gemini, set `LLM_MODEL` to a Gemini model such as `gemini-3.8-flash`. A Claude model name is replaced automatically for those two providers. Leave `WORKFLOWGPT_API_KEY` empty to keep the API open; when it is set, send it as `X-API-Key` or `Authorization: Bearer`.

Run `migrations.sql` in the Supabase SQL editor before storing runs. Re-run it if the tables already exist: it adds `n8n_workflow_json`, `errors`, and `updated_at`.

n8n can also be started with Docker from this directory:

```powershell
docker compose up -d
```

### n8n API key

1. Start n8n (self-hosted default: http://localhost:5678).
2. Complete the owner setup if prompted.
3. Open **Settings → n8n API** (or **Settings → API**).
4. Create an API key and paste it into `N8N_API_KEY`.
5. Keep `N8N_BASE_URL` as `http://localhost:5678` (no `/api/v1` suffix).

## Example

**Input instruction**

```text
When a webhook is received, POST the payload to https://httpbin.org/post.
```

**What the pipeline builds**

- Trigger: `n8n-nodes-base.webhook` (POST, path like `workflowgpt-demo`)
- Action: `n8n-nodes-base.httpRequest` to `https://httpbin.org/post`
- Connection: webhook → HTTP request

After deploy, the API returns `n8n_workflow_id` and `n8n_workflow_url` such as `http://localhost:5678/workflow/<id>`.

## Run locally

```powershell
cd workflowgpt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` to type an instruction and create the n8n workflow.

```bash
curl -X POST http://127.0.0.1:8000/generate-workflow ^
  -H "Content-Type: application/json" ^
  -d "{\"instruction\": \"When a webhook is received, POST the payload to https://httpbin.org/post.\"}"
```

On PowerShell:

```powershell
curl.exe -X POST http://127.0.0.1:8000/generate-workflow `
  -H "Content-Type: application/json" `
  -d '{"instruction": "When a webhook is received, POST the payload to https://httpbin.org/post."}'
```

Other routes: `GET /health`, `GET /workflows`, `GET /workflows/{request_id}`, `DELETE /workflows/{request_id}`.

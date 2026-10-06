# WorkflowGPT — Complete Project Documentation

**Repository:** https://github.com/Ayush-2308/WorkflowGPT  
**Application root:** `workflowgpt/`  
**Local UI:** http://127.0.0.1:8000  
**Document version:** 2026-10-06  
**GitHub commit this doc describes:** measured against local `main` (28 pytest passing)

This document is the full technical write-up of the project: purpose, architecture, how it was built, what is not included, how to run it with dummy request/response examples, and all project metrics that can be measured from the codebase.

---

## 1. One-line product definition

WorkflowGPT is a **natural-language to n8n workflow agent**: a FastAPI chat UI plus LangGraph pipeline that uses an LLM to plan (or ask for missing fields), generate n8n workflow JSON, deploy it to a self-hosted or cloud n8n instance, optionally test a webhook, and persist the run in Supabase.

It is **not** a WhatsApp/Instagram bot. Chat on port 8000 never sends a WhatsApp message. It only **designs and deploys** an n8n workflow; n8n executes automations after credentials exist there.

---

## 2. How it was built (engineering history)

Work proceeded in layers, matching git history:

| Stage | What was added |
| --- | --- |
| Scaffold | Python package, Pydantic `WorkflowSpec` / `PipelineState`, `.env` |
| Parser | Anthropic (later OpenAI + Gemini) JSON extraction + one validation retry |
| Builder + deployer | Deterministic n8n node mapping + `POST /api/v1/workflows` + activate |
| Graph | LangGraph `parse → build → deploy → test → persist` |
| Completeness | HTTP/email/document/DB/IF mapping, failure persistence, list/get/delete APIs, pytest, CI |
| Agent | Conversational planner that can **ask** for tokens/IDs then emit wide n8n JSON |
| UI | Single-page chat at `GET /` calling `POST /agent` |
| Hardening | Gemini 503 retries, `run_pipeline` import fix, `.env` never committed |

External systems wired in: **Gemini or Anthropic or OpenAI**, **n8n Public API**, **Supabase**.

---

## 3. What exists vs what does not

### Exists

- Chat UI and REST API
- Multi-turn session (`session_id`, answers, facts)
- Planner LLM → n8n JSON (catalog of common nodes + HTTP fallback)
- Fallback `WorkflowSpec` builder (webhook, schedule, form, HTTP, email, document, database, IF)
- n8n create / activate / delete / optional credential create
- Webhook or form test + execution poll
- Supabase `workflows`, `execution_logs`, `agent_sessions`
- Health check of missing env **names**
- Unit tests (28) and GitHub Actions pytest

### Does not exist

- Native “send me a WhatsApp right now” from the chat box
- Guaranteed support of every n8n community node
- OAuth login into Google/Slack/Facebook on behalf of the user
- Production Kubernetes / Terraform / full Docker app image (only optional n8n compose)
- Frontend framework (React/Next) — UI is one HTML file
- Multi-user auth / SSO (optional shared `WORKFLOWGPT_API_KEY` only)
- Horizontal scaling / Redis queue / worker pool

---

## 4. Architecture

### 4.1 System context

```
Browser (static/index.html)
        |  POST /agent
        v
FastAPI (main.py)  ---- optional X-API-Key
        |
        v
LangGraph (graph.py)
   parse/plan  ->  build  ->  deploy  ->  test  -> persist
        |             |          |          |         |
        |             |          v          v         v
        |             |        n8n API   webhook   Supabase
        v             v
     LLM APIs    n8n JSON
  (Gemini / Anthropic / OpenAI)
```

### 4.2 Request path (chat)

1. Browser keeps `workflowgpt-session` in `localStorage`.
2. `POST /agent` with `{ message, session_id, answers }`.
3. `db/sessions.py` loads facts + last 40 messages (memory, then Supabase).
4. `run_pipeline` runs the graph.
5. **parse_node** calls `plan_turn` (LLM, max 8192 tokens).
   - `mode=ask` → status `needs_input`, questions returned, **no n8n deploy**.
   - `mode=build` with `n8n_workflow` → sanitize, optional credentials, status `built`, skip deterministic builder, go to **deploy**.
   - `workflow_spec` only → **build_node** (`builder_agent`).
   - LLM total failure → parser fallback; still failing → `parse_failed`.
6. **deploy_node** `POST /api/v1/workflows` then activate. Missing n8n env → `deploy_skipped`.
7. **test_node** finds webhook (prefers `Test_webhook`) or form path; polls executions (20 × 0.75s).
8. **persist_node** upserts Supabase unless credentials missing. Successful test becomes `completed`.

### 4.3 LangGraph edges

```
START → parse
parse  → build | deploy | persist
build  → deploy | persist
deploy → test | persist
test   → persist → END
```

Nodes: `parse`, `build`, `deploy`, `test`, `persist` (5).

---

## 5. Folder map

| Path | Role |
| --- | --- |
| `workflowgpt/main.py` | FastAPI: UI, health, agent, CRUD |
| `workflowgpt/graph.py` | Pipeline orchestration |
| `workflowgpt/config.py` | Env load + `missing_settings()` |
| `workflowgpt/schemas/models.py` | Pydantic models |
| `workflowgpt/agents/planner_agent.py` | Ask vs build JSON |
| `workflowgpt/agents/parser_agent.py` | Spec parse + LLM HTTP + Gemini retries |
| `workflowgpt/agents/builder_agent.py` | Spec → n8n nodes |
| `workflowgpt/agents/n8n_sanitize.py` | LLM JSON cleanup |
| `workflowgpt/agents/n8n_catalog.py` | Node catalog text for the planner |
| `workflowgpt/agents/deployer_agent.py` | n8n REST |
| `workflowgpt/agents/executor_agent.py` | Test trigger + poll |
| `workflowgpt/agents/expressions.py` | Template → n8n expressions |
| `workflowgpt/agents/credential_apply.py` | Create/attach credentials |
| `workflowgpt/db/supabase_client.py` | Run storage |
| `workflowgpt/db/sessions.py` | Chat sessions |
| `workflowgpt/static/index.html` | Chat UI |
| `workflowgpt/migrations.sql` | Schema |
| `workflowgpt/tests/` | 9 files, 28 tests |
| `.github/workflows/test.yml` | CI pytest |

---

## 6. Environment

Copy `workflowgpt/.env.example` to `.env` (gitignored).

| Variable | Required to fully run | Notes |
| --- | --- | --- |
| `LLM_API_KEY` | Yes | Provider secret |
| `LLM_PROVIDER` | Default `anthropic` | `gemini` \| `anthropic` \| `openai` |
| `LLM_MODEL` | Has defaults | e.g. `gemini-3.8-flash` |
| `OPENAI_BASE_URL` | OpenAI only | Default official API |
| `GEMINI_BASE_URL` | Gemini only | Default Google v1beta |
| `SUPABASE_URL` | Persist | `https://PROJECT.supabase.co` |
| `SUPABASE_KEY` | Persist | **secret** key, not publishable |
| `N8N_BASE_URL` | Deploy | No `/api/v1` suffix |
| `N8N_API_KEY` | Deploy | Long JWT from n8n Settings → API |
| `WORKFLOWGPT_API_KEY` | Public hosts | Empty = open API |

Gemini 429/503: up to **4 attempts** with exponential backoff (2^attempt seconds).

---

## 7. How to start (local)

```powershell
cd workflowgpt
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# fill .env, run migrations.sql in Supabase
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

n8n must already listen on `N8N_BASE_URL` (often `http://localhost:5678`).

Browser: **http://127.0.0.1:8000**

OpenAPI: **http://127.0.0.1:8000/docs**

---

## 8. Dummy request / response (try these)

Replace `127.0.0.1:8000` if hosted elsewhere. Do **not** paste real secrets into GitHub issues.

### 8.1 Health

**Request**

```http
GET /health HTTP/1.1
Host: 127.0.0.1:8000
```

**Dummy response (configured)**

```json
{
  "status": "ok",
  "missing": [],
  "llm_provider": "gemini",
  "llm_configured": true,
  "n8n_configured": true,
  "supabase_configured": true,
  "auth_required": false
}
```

**Dummy response (incomplete)**

```json
{
  "status": "incomplete",
  "missing": ["SUPABASE_URL", "SUPABASE_KEY", "N8N_API_KEY"],
  "llm_provider": "gemini",
  "llm_configured": true,
  "n8n_configured": false,
  "supabase_configured": false,
  "auth_required": false
}
```

### 8.2 Happy path — webhook to HTTP (use this first)

**UI message (paste exactly)**

```text
When a webhook is received, POST the payload to https://httpbin.org/post.
```

**Equivalent HTTP**

```http
POST /agent HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json

{
  "message": "When a webhook is received, POST the payload to https://httpbin.org/post."
}
```

**Dummy success response (shape from a real local run)**

```json
{
  "request_id": "a1b7f0ed-c185-491c-889f-b1727cced659",
  "raw_instruction": "When a webhook is received, POST the payload to https://httpbin.org/post.",
  "deployment_status": "completed",
  "n8n_workflow_id": "qDz8dpjzoMQ4PO5M",
  "n8n_workflow_url": "http://localhost:5678/workflow/qDz8dpjzoMQ4PO5M",
  "assistant_message": "Deployed a webhook that forwards the body to httpbin.",
  "questions": [],
  "errors": [],
  "session_id": "11111111-2222-3333-4444-555555555555",
  "test_result": {
    "status": "success",
    "webhook": {
      "url": "http://localhost:5678/webhook/workflowgpt-demo",
      "method": "POST"
    }
  }
}
```

What you should see in the UI: a green user bubble, then a bot message plus an **n8n link**. Opening the link shows Webhook → HTTP Request.

### 8.3 Agent asks for missing fields

**Request**

```json
{
  "message": "Comment on new Facebook leads from Maharashtra."
}
```

**Dummy `needs_input` response**

```json
{
  "deployment_status": "needs_input",
  "n8n_workflow_id": null,
  "n8n_workflow_url": null,
  "assistant_message": "I can build this in n8n, but I need access details.",
  "questions": [
    {
      "id": "page_id",
      "prompt": "What is the Facebook Page ID?",
      "secret": false,
      "placeholder": "123456789"
    },
    {
      "id": "page_token",
      "prompt": "Paste a Page access token.",
      "secret": true,
      "placeholder": ""
    }
  ],
  "errors": []
}
```

**Follow-up (same session)**

```json
{
  "session_id": "11111111-2222-3333-4444-555555555555",
  "message": "Here are the details you asked for.",
  "answers": {
    "page_id": "123456789",
    "page_token": "EAAB...redacted"
  }
}
```

Then the pipeline may `build` + `deploy`. Facebook Graph still needs a valid token; dummy values will deploy a workflow that fails at runtime.

### 8.4 Gemini busy (seen in production)

**Same webhook prompt**, LLM returns HTTP 503 twice (plan + retry).

**Dummy error payload**

```json
{
  "deployment_status": "parse_failed",
  "assistant_message": "I could not plan this automation yet.",
  "n8n_workflow_url": null,
  "errors": [
    "parse failed after validation retry: Gemini request failed with status 503: This model is currently experiencing high demand."
  ]
}
```

This is **not** a bad prompt. Wait and resend. Current code retries 503/429 up to four times per LLM call.

### 8.5 List runs

```http
GET /workflows?limit=8 HTTP/1.1
```

```json
{
  "workflows": [
    {
      "request_id": "a1b7f0ed-c185-491c-889f-b1727cced659",
      "raw_instruction": "When a webhook is received, POST the payload to https://httpbin.org/post.",
      "status": "completed",
      "n8n_workflow_id": "qDz8dpjzoMQ4PO5M",
      "n8n_workflow_url": "http://localhost:5678/workflow/qDz8dpjzoMQ4PO5M"
    }
  ]
}
```

### 8.6 Delete

```http
DELETE /workflows/a1b7f0ed-c185-491c-889f-b1727cced659 HTTP/1.1
```

```json
{
  "request_id": "a1b7f0ed-c185-491c-889f-b1727cced659",
  "n8n_deleted": true
}
```

---

## 9. HTTP surface (complete)

| Method | Path | Auth if key set | Purpose |
| --- | --- | --- | --- |
| GET | `/` | No | Chat HTML |
| GET | `/health` | No | Config flags |
| GET | `/docs` | No | FastAPI Swagger |
| POST | `/agent` | Yes | Chat turn |
| POST | `/generate-workflow` | Yes | Same pipeline; `instruction` field |
| GET | `/workflows` | Yes | List |
| GET | `/workflows/{request_id}` | Yes | Detail |
| DELETE | `/workflows/{request_id}` | Yes | n8n + DB delete |

**Count: 7 application routes** (+ `/docs`, `/openapi.json` from FastAPI).

Auth header: `X-API-Key` or `Authorization: Bearer`.

---

## 10. Data models and database

### PipelineState (API + graph)

`request_id`, `raw_instruction`, `workflow_spec`, `n8n_workflow_json`, `n8n_workflow_id`, `deployment_status`, `test_result`, `errors`, `assistant_message`, `questions`, `facts` (secrets redacted in HTTP as `••••` when the key name looks secret), `conversation`, `session_id`.

### WorkflowSpec (builder fallback)

`name`, `description`, `trigger{type,config}`, `actions[{type,config,depends_on}]`, `raw_instruction`.

### Tables (migrations.sql)

| Table | Keys / notes |
| --- | --- |
| `workflows` | PK `request_id`; JSON spec + n8n JSON; status; errors |
| `execution_logs` | FK `request_id` ON DELETE CASCADE |
| `agent_sessions` | PK `session_id`; `facts` (may hold tokens); `messages` |

RLS enabled with permissive service-role policies.

---

## 11. Status dictionary

| Status | Meaning |
| --- | --- |
| `pending` | Graph start |
| `needs_input` | Waiting on user questions |
| `parsed` | Spec ready, builder next |
| `built` | n8n JSON ready |
| `deployed` | n8n id assigned |
| `tested` | Test finished (then stored as `completed`) |
| `completed` | Successful test persisted |
| `parse_failed` | Plan/parse failed |
| `build_failed` | JSON/spec mapping failed |
| `deployment_failed` | n8n API error |
| `deploy_skipped` | n8n env empty |
| `test_failed` | Trigger/poll failed |
| `test_skipped` | No webhook/form to hit |
| `store_failed` | Supabase write failed |
| `error` | `log_error` crash path |

---

## 12. Technical metrics (measured 2026-10-06)

Figures exclude `node_modules`, `.venv`, `.tools`, `__pycache__`, `.git`.

### Size and structure

| Metric | Value |
| --- | --- |
| Python files | 29 (20 application, 9 test) |
| Python raw lines | 3773 (src 3250, tests 523) |
| Python LOC (non-blank, non-`#`) | 3292 (src 2850, tests 442) |
| Chat UI HTML lines | 228 |
| Markdown lines (repo docs before this refresh) | ~521 |
| Tracked text-ish source files counted | 40 |
| Agent modules under `agents/` | 10 Python files |
| Graph nodes | 5 |
| Conditional edge groups | 3 |
| HTTP app routes | 7 |
| LLM providers implemented | 3 |
| Env keys in `.env.example` | 10 |
| Supabase tables | 3 |
| pytest files | 9 |
| pytest tests | **28 passed** (runtime ~11.4 s on this machine) |
| GitHub Actions jobs | 1 (`pytest` on Python 3.12) |
| Documented git commits on `main` (at measure) | 6 |

### Runtime / limits (from code)

| Metric | Value |
| --- | --- |
| FastAPI bind (docs) | `127.0.0.1:8000` local; `0.0.0.0:8000` for hosts |
| Default n8n | `http://localhost:5678` |
| LLM HTTP timeout | 60 s |
| n8n HTTP timeout | 30 s |
| Gemini max output (chat) | 4096 default; planner 8192 |
| Gemini transient retries | 4 (status 429, 503) |
| Parser validation retries | 1 extra LLM call |
| Execution poll | 20 attempts × 0.75 s ≈ 15 s |
| Session messages kept | last 40 |
| Workflow list cap | 1–200 (default 50) |
| Health `missing` | names only, never secret values |

### Test breakdown (28)

| File | Tests |
| --- | --- |
| `test_api.py` | 4 |
| `test_builder.py` | 4 |
| `test_deployer.py` | 2 |
| `test_executor.py` | 4 |
| `test_expressions.py` | 2 |
| `test_graph.py` | 3 |
| `test_parser.py` | 5 |
| `test_planner.py` | 2 |
| `test_sanitize.py` | 2 |

Coverage style: **unit tests with mocks**; no live Gemini/n8n in CI.

### Builder catalog (deterministic path)

Triggers: webhook, schedule, form_submission.  
Actions: http_request, send_email, generate_document, database_insert (+ IF on `condition`).  
Planner catalog additionally steers toward Slack, Gmail, Sheets, Telegram, Postgres, HTTP, Code, Switch, etc.

### Dependencies (requirements.txt)

fastapi, uvicorn, langgraph, pydantic, python-dotenv, supabase, httpx, anthropic, pytest (minimum versions pinned with `>=`).

No React, no Redis, no Celery.

---

## 13. Security metrics / practices

| Item | Behavior |
| --- | --- |
| `.env` in git | Ignored |
| Health endpoint | Does not echo secrets |
| API `facts` | Keys matching token/secret/password/key/authorization/cookie → `••••` |
| Public deploy | Set `WORKFLOWGPT_API_KEY` |
| Supabase key | Server `sb_secret_`, never `sb_publishable_` |
| n8n key | JWT; short UI ids are rejected (401) |
| Session facts | Stored in DB — treat Supabase as sensitive |

---

## 14. Deploy notes

Hosting the GitHub repo is **not** a running product. You must run WorkflowGPT **and** an n8n the API can reach.

- Same machine: uvicorn + local n8n.
- Internet: Render/Railway for the API **and** n8n Cloud/VPS. `N8N_BASE_URL` must be the public n8n URL. Cloud API + laptop `localhost:5678` will fail deploy.

Start command from `workflowgpt/`:

```text
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## 15. Cross-check (documentation vs code)

Verified against the tree on 2026-10-06:

| Claim | Evidence |
| --- | --- |
| Chat UI at `/` | `main.py` `home()` reads `static/index.html` |
| Agent POST `/agent` | `main.py` `agent_turn` |
| Graph 5 nodes | `build_graph()` in `graph.py` |
| 28 tests pass | `pytest -q` → `28 passed in 11.41s` |
| 7 app routes | `@app.get/post/delete` in `main.py` |
| 3 LLM providers | `_call_llm` branches in `parser_agent.py` |
| 3 SQL tables | `migrations.sql` |
| Gemini retry | `_call_gemini` loop `range(4)` |
| Secrets not in git | `.gitignore` contains `.env` |
| Planner ask/build | `agents/planner_agent.py` `AgentPlan.mode` |
| Dummy happy path used in real demo | Local deploy ids such as `qDz8dpjzoMQ4PO5M` were created on this machine; ids on your n8n will differ |

If a later commit adds routes or tests, re-run pytest and update section 12.

---

## 16. Troubleshooting

| Symptom | Action |
| --- | --- |
| `parse_failed` + Gemini 503 | Wait, retry same webhook prompt |
| `run_pipeline is not defined` | Restart uvicorn after pull |
| n8n 401 | Use full API JWT, not list id |
| Empty history | Run `migrations.sql`; check Supabase keys |
| WhatsApp not arriving | Expected — app does not send WhatsApp |

---

## 17. License / data ownership

Source: GitHub `Ayush-2308/WorkflowGPT`.  
Runtime secrets and workflow data live in the operator’s `.env`, n8n, and Supabase — not in the public repo.

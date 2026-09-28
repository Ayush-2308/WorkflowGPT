-- WorkflowGPT Supabase schema
-- Safe to re-run. Existing tables keep their rows; new columns are added below.

create table if not exists public.workflows (
    request_id text primary key,
    raw_instruction text not null,
    workflow_spec jsonb,
    n8n_workflow_json jsonb,
    n8n_workflow_id text,
    status text not null default 'pending',
    errors jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.execution_logs (
    id bigserial primary key,
    request_id text not null references public.workflows (request_id) on delete cascade,
    test_result jsonb,
    created_at timestamptz not null default now()
);

create index if not exists execution_logs_request_id_idx
    on public.execution_logs (request_id);

alter table public.workflows add column if not exists n8n_workflow_json jsonb;
alter table public.workflows add column if not exists errors jsonb not null default '[]'::jsonb;
alter table public.workflows add column if not exists updated_at timestamptz not null default now();

alter table public.workflows enable row level security;
alter table public.execution_logs enable row level security;

drop policy if exists workflows_api_access on public.workflows;
create policy workflows_api_access on public.workflows
    for all
    using (true)
    with check (true);

create table if not exists public.agent_sessions (
    session_id text primary key,
    facts jsonb not null default '{}'::jsonb,
    messages jsonb not null default '[]'::jsonb,
    updated_at timestamptz not null default now()
);

alter table public.agent_sessions enable row level security;
drop policy if exists agent_sessions_api_access on public.agent_sessions;
create policy agent_sessions_api_access on public.agent_sessions
    for all
    using (true)
    with check (true);
create policy execution_logs_api_access on public.execution_logs
    for all
    using (true)
    with check (true);

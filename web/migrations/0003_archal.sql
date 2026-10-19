-- Archal product API. Same rows the desk already shows, plus keys, sessions, and workflow records.

create table if not exists archal_tenants (
  id text primary key,
  name text not null,
  segment text not null,
  refund_cap integer not null,
  killed boolean not null default false,
  live_enabled boolean not null default false,
  sandbox_passed_at timestamptz,
  daily_cap integer not null default 2000,
  used_today integer not null default 0,
  webhook_url text
);

insert into archal_tenants (id, name, segment, refund_cap, used_today)
select id, name, segment, refund_cap, 0 from brands
on conflict (id) do nothing;

create table if not exists archal_keys (
  token text primary key,
  tenant_id text not null references archal_tenants (id),
  role text not null,
  mode text not null default 'test'
);

insert into archal_keys (token, tenant_id, role, mode) values
  ('archal_test_n4k2', 'northline', 'widget', 'test'),
  ('archal_sup_n4k2', 'northline', 'supervisor', 'test'),
  ('archal_test_m8p1', 'mira', 'widget', 'test'),
  ('archal_sup_m8p1', 'mira', 'supervisor', 'test')
on conflict (token) do nothing;

create table if not exists archal_sessions (
  id text primary key,
  tenant_id text not null,
  customer_ref text not null,
  created_at timestamptz not null default now()
);

create table if not exists archal_cases (
  id text primary key,
  brand_id text not null,
  channel text not null,
  customer_label text not null,
  customer_ref text not null,
  subject text not null,
  preview text not null,
  intent text not null,
  status text not null,
  priority text not null,
  ai_handled boolean not null default true,
  confidence integer not null default 80,
  amount_inr integer,
  order_ref text,
  assignee text not null default 'Archal',
  escalated boolean not null default false,
  missing_inputs text not null default '',
  citations text not null default '',
  opened_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

insert into archal_cases (
  id, brand_id, channel, customer_label, customer_ref, subject, preview, intent, status, priority,
  ai_handled, confidence, amount_inr, order_ref, assignee, opened_at, updated_at
)
select
  id, brand_id, channel, customer_label, customer_label, subject, preview, intent, status, priority,
  ai_handled, confidence, amount_inr, order_ref, assignee, opened_at, updated_at
from conversations
on conflict (id) do nothing;

create table if not exists archal_messages (
  id serial primary key,
  conversation_id text not null,
  author text not null,
  body text not null,
  citation text,
  created_at timestamptz not null default now()
);

insert into archal_messages (conversation_id, author, body, citation, created_at)
select conversation_id, case when author = 'kivo' then 'archal' else author end, body, citation, created_at
from messages;

create table if not exists archal_tasks (
  id text primary key,
  tenant_id text not null,
  case_id text not null,
  task_type text not null,
  status text not null,
  amount integer,
  order_ref text,
  note text
);

insert into archal_tasks (id, tenant_id, case_id, task_type, status, amount, order_ref)
select 'task_' || id, brand_id, id, 'refund_approval', 'pending', amount_inr, order_ref
from archal_cases
where status = 'waiting_approval'
on conflict (id) do nothing;

create table if not exists archal_runs (
  id text primary key,
  tenant_id text not null,
  case_id text not null,
  workflow_name text not null,
  status text not null,
  current_step text,
  error text,
  output_json text not null default '{}'
);

insert into archal_runs (id, tenant_id, case_id, workflow_name, status, current_step)
select 'run_' || id, brand_id, id, 'support.turn', status, 'reply'
from archal_cases
on conflict (id) do nothing;

create table if not exists archal_steps (
  id serial primary key,
  run_id text not null,
  step_index integer not null,
  step_name text not null,
  status text not null,
  attempt integer not null default 1,
  error text
);

insert into archal_steps (run_id, step_index, step_name, status)
select 'run_' || id, 1, 'policy', 'succeeded' from archal_cases;

insert into archal_steps (run_id, step_index, step_name, status)
select 'run_' || id, 2, 'tools', case when status = 'waiting_approval' then 'skipped' else 'succeeded' end
from archal_cases;

create table if not exists archal_interactions (
  id text primary key,
  tenant_id text not null,
  case_id text,
  customer_ref text,
  intent text,
  outcome text,
  escalated boolean not null default false,
  created_at timestamptz not null default now()
);

insert into archal_interactions (id, tenant_id, case_id, customer_ref, intent, outcome, escalated, created_at)
select 'int_' || id, brand_id, id, customer_label, intent, status, false, updated_at
from archal_cases
on conflict (id) do nothing;

create table if not exists archal_docs (
  id text primary key,
  tenant_id text not null,
  name text not null,
  bytes integer not null,
  status text not null,
  error text
);

insert into archal_docs (id, tenant_id, name, bytes, status) values
  ('snap_northline_v1', 'northline', 'Northline terms of use.pdf', 240000, 'ready'),
  ('snap_mira_v1', 'mira', 'Mira pantry policy.pdf', 180000, 'ready')
on conflict (id) do nothing;

create table if not exists archal_accounts (
  email text primary key,
  password_hash text not null,
  tenant_id text not null,
  created_at timestamptz not null default now()
);

create table if not exists archal_owner_sessions (
  token text primary key,
  tenant_id text not null,
  created_at timestamptz not null default now()
);

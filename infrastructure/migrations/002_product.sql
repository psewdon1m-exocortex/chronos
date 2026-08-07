alter table time_sessions
    add column if not exists note text not null default '',
    add column if not exists source text not null default 'telegram',
    add column if not exists updated_at timestamptz not null default now(),
    add column if not exists deleted_at timestamptz;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'time_sessions_source_check'
    ) then
        alter table time_sessions add constraint time_sessions_source_check
            check (source in ('telegram', 'web', 'manual', 'restore'));
    end if;
end
$$;

with ranked as (
    select id,
           row_number() over (partition by user_id order by started_at desc, id desc) as position
    from time_sessions
    where stopped_at is null and deleted_at is null
)
update time_sessions session
set stopped_at = session.started_at,
    duration_seconds = 0,
    updated_at = now()
from ranked
where session.id = ranked.id and ranked.position > 1;

create unique index if not exists idx_time_sessions_one_active
    on time_sessions (user_id)
    where stopped_at is null and deleted_at is null;

create index if not exists idx_time_sessions_period
    on time_sessions (user_id, started_at, stopped_at)
    where deleted_at is null;

create table if not exists app_settings (
    key text primary key,
    value jsonb not null,
    updated_at timestamptz not null default now()
);

create table if not exists operator_security (
    id smallint primary key default 1 check (id = 1),
    username text not null,
    password_hash text not null,
    session_generation integer not null default 1,
    updated_at timestamptz not null default now()
);

create table if not exists telegram_link_codes (
    id bigserial primary key,
    code_hash text not null,
    expires_at timestamptz not null,
    consumed_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists undo_actions (
    id bigserial primary key,
    user_id bigint not null references users(id) on delete cascade,
    action text not null,
    before_state jsonb not null default '[]'::jsonb,
    after_ids jsonb not null default '[]'::jsonb,
    used_at timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists idx_undo_actions_latest
    on undo_actions (user_id, created_at desc)
    where used_at is null;

create table if not exists audit_events (
    id bigserial primary key,
    status text not null check (status in ('success', 'error', 'denied', 'info')),
    action text not null,
    target text not null default '',
    actor text not null default 'system',
    message text not null default '',
    details jsonb not null default '{}'::jsonb,
    request_id text,
    created_at timestamptz not null default now()
);

create index if not exists idx_audit_events_created
    on audit_events (created_at desc);


create table if not exists gryphon_events (
    event_id text primary key,
    state text not null check (state in ('processing', 'completed', 'failed')),
    response jsonb,
    created_at timestamptz not null default now(),
    started_at timestamptz not null default now(),
    completed_at timestamptz
);

create index if not exists idx_gryphon_events_created_at
    on gryphon_events (created_at);

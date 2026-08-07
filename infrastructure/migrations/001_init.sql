create table if not exists users (
    id bigserial primary key,
    tg_user_id bigint not null unique,
    created_at timestamptz not null default now()
);

create table if not exists time_sessions (
    id bigserial primary key,
    user_id bigint not null references users(id) on delete cascade,
    category text not null check (category in (
        'recovery',
        'accumulation',
        'execution',
        'maintenance'
    )),
    started_at timestamptz not null,
    stopped_at timestamptz,
    duration_seconds integer,
    created_at timestamptz not null default now()
);

create index if not exists idx_time_sessions_user_started
    on time_sessions (user_id, started_at desc);


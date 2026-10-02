create table if not exists monthly_reports (
    month char(7) primary key,
    timezone text not null,
    template_path text not null,
    state text not null check (state in ('pending', 'processing', 'delivered')),
    template_sha256 text,
    body text,
    attempts integer not null default 0,
    last_error text not null default '',
    next_attempt_at timestamptz not null default now(),
    lease_until timestamptz,
    mastermind_path text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    delivered_at timestamptz
);

create index if not exists idx_monthly_reports_due
    on monthly_reports (next_attempt_at, month)
    where state <> 'delivered';

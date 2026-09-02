create table if not exists service_credentials (
    id smallint primary key default 1 check (id = 1),
    kernel_url text not null default '',
    kernel_token_ciphertext text not null default '',
    updated_at timestamptz not null default now()
);

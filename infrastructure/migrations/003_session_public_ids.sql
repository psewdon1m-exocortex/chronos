alter table time_sessions
    add column if not exists public_id text;

update time_sessions
set public_id = 't-' || repeat('0', greatest(0, 8 - length(id::text))) || id::text
where public_id is null;

create or replace function chronos_assign_time_session_public_id()
returns trigger
language plpgsql
as $$
begin
    if new.public_id is null or new.public_id = '' then
        new.public_id := 't-' ||
            repeat('0', greatest(0, 8 - length(new.id::text))) ||
            new.id::text;
    end if;
    return new;
end
$$;

drop trigger if exists trg_time_sessions_public_id on time_sessions;

create trigger trg_time_sessions_public_id
before insert on time_sessions
for each row
execute function chronos_assign_time_session_public_id();

alter table time_sessions
    alter column public_id set not null;

create unique index if not exists idx_time_sessions_public_id
    on time_sessions (public_id);

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'time_sessions_public_id_check'
    ) then
        alter table time_sessions add constraint time_sessions_public_id_check
            check (public_id ~ '^t-[0-9]{8,}$');
    end if;
end
$$;

alter table time_sessions
    add column if not exists carried_seconds integer not null default 0;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'time_sessions_carried_seconds_check'
    ) then
        alter table time_sessions add constraint time_sessions_carried_seconds_check
            check (carried_seconds >= 0);
    end if;
end
$$;

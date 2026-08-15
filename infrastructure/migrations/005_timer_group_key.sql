alter table time_sessions
    add column if not exists timer_group_key text;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'time_sessions_timer_group_key_check'
    ) then
        alter table time_sessions add constraint time_sessions_timer_group_key_check
            check (timer_group_key is null or timer_group_key ~ '^t-[0-9]{8,}$');
    end if;
end
$$;

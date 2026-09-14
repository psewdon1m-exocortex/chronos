create table if not exists revoked_sessions (
    token_hash text primary key,
    expires_at timestamptz not null
);
create index if not exists idx_revoked_sessions_expiry on revoked_sessions(expires_at);
-- Older releases could persist a timer mutation before the command response.
-- Preserve uncertain command IDs across upgrade without replaying the mutation.
UPDATE gryphon_events SET state='completed', completed_at=now(),
  response='{"schema":"exocortex.telegram.response.v1","actions":[{"type":"send_message","text":"This command was interrupted before upgrade. Check the timer state and submit a new command if needed."}]}'::jsonb
WHERE state='processing';

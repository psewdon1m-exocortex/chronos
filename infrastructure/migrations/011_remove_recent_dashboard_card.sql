-- RECENT moved to Timeline; normalize dashboard layouts saved by older releases.
update app_settings
set value = value - 'recent', updated_at = now()
where key = 'dashboard_order'
  and jsonb_typeof(value) = 'array'
  and value ? 'recent';

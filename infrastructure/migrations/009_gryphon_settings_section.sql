update app_settings
set value = case
  when value ? 'gryphon' then value
  else value || '["gryphon"]'::jsonb
end
where key = 'settings_order';

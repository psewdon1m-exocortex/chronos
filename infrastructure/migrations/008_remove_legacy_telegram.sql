drop table if exists telegram_link_codes;

alter table users drop column if exists tg_user_id;

update app_settings
set value = value - 'telegram', updated_at = now()
where key = 'settings_order' and value ? 'telegram';

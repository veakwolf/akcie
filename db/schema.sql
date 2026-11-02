-- Akcie Trnava: shared shopping list + watch list ("household"), no logins.
-- Whoever knows a household's code can read and write it, so the code acts as a password.
-- Paste this whole file into Supabase → SQL Editor → Run. Safe to run again.

create table if not exists public.households (
  code        text primary key check (char_length(code) >= 12),
  data        jsonb not null default '{}'::jsonb,   -- { list: [...], watch: [...] }
  updated_at  timestamptz not null default now()
);

-- Row level security ON and no policies: the table can't be read or listed directly.
-- The app only goes through the two functions below, which need the exact code.
alter table public.households enable row level security;

create or replace function public.get_household(p_code text)
returns jsonb
language sql
security definer
set search_path = public
as $$
  select jsonb_build_object('data', data, 'updated_at', updated_at)
  from households where code = p_code
$$;

create or replace function public.save_household(p_code text, p_data jsonb)
returns timestamptz
language plpgsql
security definer
set search_path = public
as $$
declare
  t timestamptz := now();
begin
  if char_length(coalesce(p_code, '')) < 12 then
    raise exception 'code too short';
  end if;
  if pg_column_size(p_data) > 200000 then
    raise exception 'data too large';
  end if;
  insert into households (code, data, updated_at) values (p_code, p_data, t)
  on conflict (code) do update set data = excluded.data, updated_at = t;
  return t;
end
$$;

revoke all on function public.get_household(text) from public;
revoke all on function public.save_household(text, jsonb) from public;
grant execute on function public.get_household(text) to anon, authenticated;
grant execute on function public.save_household(text, jsonb) to anon, authenticated;

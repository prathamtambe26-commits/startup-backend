-- ─────────────────────────────────────────────
--  USERS TABLE
-- ─────────────────────────────────────────────
create table users (
  id           uuid primary key default gen_random_uuid(),
  phone_number text unique not null,
  name         text default '',
  state        text default 'awaiting_name',  -- awaiting_name | awaiting_confirmation | active
  created_at   timestamp default now()
);

-- ─────────────────────────────────────────────
--  TRANSACTION TABLE
-- ─────────────────────────────────────────────
create table transaction (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid references users(id) on delete cascade,
  amount     numeric not null,
  keyword    text,
  category   text,               -- food | transport | shopping | health | bills | entertainment | income | other
  type       text,               -- expense | income
  created_at timestamp default now()
);

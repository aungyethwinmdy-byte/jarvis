-- ============================================================================
--  categorized_news — the JARVIS state-paper table
--  Project: jarvis  (yrzvwsqafmftbrfwimsf)
--  Run once in:  Supabase dashboard → SQL Editor → New query → paste → Run
-- ============================================================================
--
--  WHY THIS FILE EXISTS
--
--  JARVIS's spec calls for a `categorized_news` table in the `jarvis` project.
--  Measured 2026-10-01: that table does not exist there — the project exposes
--  only `news_articles`, `independent_articles`, `news_reports` and
--  `system_run_logs` — and **PostgREST cannot create it**. There is no
--  `exec_sql` / `exec` RPC in this project either (its only two RPCs are
--  `show_limit` and `show_trgm`, both pg_trgm helpers), so DDL is not reachable
--  from the application side at all.
--
--  So this is the one step that has to be done by hand. Everything after it
--  (classifying the 7,193 state-paper articles into the 16 categories and
--  filling the table) is automated.
--
--  The 16 categories are exactly the owner's 15 plus `အခြား`, which he asked
--  for on 2026-10-01 because 69% of the readable corpus — advertisements,
--  announcements, sport, regional notices — matches none of the 15.
-- ============================================================================

create table if not exists public.categorized_news (
    id             uuid primary key default gen_random_uuid(),
    issue_date     date        not null,
    newspaper_name text        not null,
    category       text        not null,
    headline       text        not null,
    summary        text,
    full_content   text,
    page_number    text,
    created_at     timestamptz not null default now(),

    constraint categorized_news_paper_chk
        check (newspaper_name in ('မြန်မာ့အလင်း', 'ကြေးမုံ')),

    -- The 15 official categories plus the `အခြား` bucket. A CHECK rather than a
    -- lookup table on purpose: a category that is not on the owner's list must
    -- be refused at the database, not silently stored. Adding a 17th later is a
    -- one-line migration.
    constraint categorized_news_category_chk
        check (category in (
            'နိုင်ငံတော်သမ္မတ',
            'ဒုတိယသမ္မတဦးညိုစော',
            'ဒုတိယသမ္မတဒေါ်နန်းနီနီအေး',
            'ပြည်ထောင်စုဝန်ကြီးများ',
            'အမျိုးသားလွှတ်တော်',
            'ပြည်သူ့လွှတ်တော်',
            'ပြည်ထောင်စုလွှတ်တော်',
            'နိုင်ငံရေး',
            'စီးပွားရေး',
            'လူမှုရေး',
            'ပညာရေး',
            'ကျန်းမာရေး',
            'သဘာဝဘေးအန္တရာယ်သတင်းများ',
            'ဆောင်းပါးများ',
            'အယ်ဒီတာ့အာဘော်',
            'အခြား'
        ))
);

-- Answering "what is in today's နိုင်ငံတော်သမ္မတ category" is the whole point,
-- so the index is (category, date) and not the other way round.
create index if not exists categorized_news_date_idx
    on public.categorized_news (issue_date desc);

create index if not exists categorized_news_cat_date_idx
    on public.categorized_news (category, issue_date desc);

-- Re-running the classifier must not duplicate a story. `md5(headline)` because
-- a raw btree on a long text can exceed the index row limit.
create unique index if not exists categorized_news_dedup_idx
    on public.categorized_news (issue_date, newspaper_name, md5(headline));

-- The pipeline writes with the service key, so RLS is not in the way; this is
-- here so a future read-only key can be used for JARVIS itself.
alter table public.categorized_news enable row level security;

drop policy if exists categorized_news_read on public.categorized_news;
create policy categorized_news_read on public.categorized_news
    for select using (true);

-- ============================================================================
--  After running this, tell me — the next step is automated:
--    read the 7,193 state-paper articles from the reporter project
--    (zdsxuxwonkovuesjepfa), classify each into one of the 16 categories, and
--    insert them here.
-- ============================================================================

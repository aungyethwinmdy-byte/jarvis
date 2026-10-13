# my_reporter ↔ JARVIS — integration analysis

Study of `E:\test\my_reporter-main` (297 files) against the JARVIS newsroom bridge in
`E:\Mark-LIV-main`, with every claim below measured rather than inferred.

---

## 1. What my_reporter actually is

A Myanmar newspaper intelligence pipeline, not a single script. Twelve working modules:

| module | what it does |
|---|---|
| `ingest_engine.py` | pulls **Myanma Alinn** and **The Mirror** PDFs from Google Drive into Supabase `articles`; reads the Page-2 fuel/gold table with `pdfplumber` |
| `auto_numeric_extractor.py` | pulls prices, commodity rates and statistics out of those articles into `newspaper_numbers` |
| `fetch_independent_news.py` | ingests **BBC Burmese** (RSS) and **The Irrawaddy** (via its Telegram mirror — a deliberate bypass of a Cloudflare 403) |
| `cross_source_verifier.py` | plans keywords, fetches state and independent coverage, and writes a **divergence report** with Gemini |
| `numeric_intelligence_engine.py` | answers price questions from `newspaper_numbers` — `is_numeric_or_price_query`, `query_exact_numbers` |
| `newsroom_mcp.py` | MCP server (SSE) exposing four read-only tools |
| `notifications.py`, `database.py` | Telegram delivery; a SQLite `download_history` |
| `main.py` | orchestrator |
| `gemini_config.py`, `env_config.py`, `number_utils.py` | shared plumbing — model choice, validated env readers, numeric-text helpers |
| `SKILL.md` | a **state policy editor**: rewrites notes into Myanma Alinn / Kyemon house style |

The MCP server exposes exactly four RPCs: `fn_search_news`, `fn_get_event_timeline`,
`fn_compare_sources`, `fn_get_daily_briefing`.

---

## 2. The two databases are separate — measured

| | Supabase project | outlets |
|---|---|---|
| **JARVIS** (`E:\Mark-LIV-main`) | `yrzvwsqafmftbrfwimsf` | PPIB, BBC Burmese, The Irrawaddy |
| **my_reporter** | `zdsxuxwonkovuesjepfa` | Myanma Alinn, The Mirror, BBC Burmese, The Irrawaddy |

Different URLs, different service keys. **Nothing is shared today.**

Live row counts, read-only:

| table | rows |
|---|---|
| `articles` (my_reporter) | **6,921** |
| `newspaper_numbers` (my_reporter) | **376** |

JARVIS's own bridge answers: `available() → True`, `recent_reports() → 10`,
`search_articles('ဆီဈေး') → 3 hits`. Both sides are alive and populated.

---

## 3. The finding that matters

**The two systems have independently converged on the same four capabilities, over two
separate databases.**

| capability | JARVIS tool | my_reporter |
|---|---|---|
| keyword search | `newsroom_search` | `fn_search_news` |
| story timeline | `newsroom_story` | `fn_get_event_timeline` |
| compare outlets | `newsroom_compare` | `fn_compare_sources` |
| daily briefing | `newsroom_digest` | `fn_get_daily_briefing` |

That reframes the whole question. The integration is **not "build a second system"** — it
is **"point the four tools JARVIS already has at a second database."**

**And the coverage is complementary, not duplicated:**

- **JARVIS has PPIB.** my_reporter does not.
- **my_reporter has Myanma Alinn and The Mirror** — the two state newspapers. JARVIS does not.
- **Both fetch BBC Burmese and The Irrawaddy**, separately, into different tables. That is
  the only real duplication, and it is worth noting as waste rather than as a feature.

**Two things in my_reporter that JARVIS has nothing like:**

1. **`newspaper_numbers`** — 376 verified price rows, Page-2 fuel and gold, extracted with
   `pdfplumber`. `is_numeric_or_price_query()` + `query_exact_numbers()` answer *"ဒီနေ့
   ဆီဈေး ဘယ်လောက်လဲ"* from stored figures instead of from the model's memory. **This is
   the single most valuable thing in the repository** for a journalist, and the one piece
   JARVIS cannot fake.
2. **`cross_source_verifier.run_cross_source_comparison(topic)`** — a full divergence
   report. JARVIS's `newsroom_compare` does something similar on its own data, but the
   two were written independently and have never been compared.

---

## 4. Options, with what each is worth

### Option A — a second read-only bridge (recommended)

Mirror `core/newsroom_client.py` as `core/reporter_client.py`: own env path, own
credentials, same shape (`available()`, `_cached()`, returns a default on a stall so the
voice path never raises). Then four new tools in `actions/`, one `TOOL` dict per file, as
the project requires.

- **Gains:** state newspapers in JARVIS; `newspaper_numbers`; a second comparison source.
- **Effort:** low — the pattern exists and is proven.
- **Risk:** low. Read-only, separate credentials, and the existing `_cached()` guard means
  a Supabase stall makes the answer thinner, not an apology.
- **Cost:** two more credentials to keep alive, four more tools in the prompt.

### Option B — JARVIS as an MCP client of the newsroom server

Call `newsroom_mcp.py` over SSE instead of reading Supabase directly.

- **Gains:** reuses the server's RPC wrappers and its `limit` clamping.
- **Why I would not:** JARVIS already reads Supabase directly and has done so reliably.
  This adds a network hop, a second process to keep running, and an MCP client — to avoid
  writing four small functions. The MCP server's real purpose is LLM clients that cannot
  reach the database themselves; JARVIS is not one of those.

### Option C — remove the duplicated ingestion

One system ingests BBC Burmese and The Irrawaddy; the other reads it.

- **Gains:** less work, one copy of each article, no chance of the two disagreeing.
- **Why it is not first:** it couples the two projects. If my_reporter is ever run on
  another machine, or stopped, JARVIS loses two of its three outlets. **Worth doing later,
  deliberately, with one writer named in advance** — the project already has this rule for
  `E:\AI_NEWSROOM` ("one writer, one reader").

### Option D — compare the two verifiers

Put `cross_source_verifier.py` beside JARVIS's `check_coverage.py` and see which classifies
COVERED / NOT_COVERED / UNCLEAR more honestly. JARVIS's version was rewritten on 2026-09-27
because naming an outlet was being counted as covering it.

- **Gains:** possibly a better verifier, or confirmation that the current one is right.
- **Effort:** a reading exercise, not a build.

---

## 5. What I would do first

**Option A, scoped to the numbers.** The state newspapers are valuable, but
`newspaper_numbers` is the part with no equivalent anywhere in JARVIS, and it is 376 rows —
small enough to get right quickly.

1. `core/reporter_client.py` — read-only, `newspaper_numbers` and `articles`, with the same
   `_cached()` discipline as the existing bridge.
2. `actions/reporter_prices.py` — one TOOL. *"ဒီနေ့ ဆီဈေး ဘယ်လောက်လဲ"* → the stored
   figure, with its date, never a guess.
3. Then `actions/reporter_state_news.py` — the four RPCs, if step 1-2 prove the credentials
   and the latency are sound.

**Before any of it:** the same lesson this week has already taught twice — **check the
credentials load and one real query returns before writing the tool**, not after.

---

## 6. Cautions

- **Two service-role keys on one machine.** Both are full-access. They must stay out of
  logs, out of the model's context, and out of any file that gets committed. JARVIS's rule
  already applies: verify a credential write by key **counts**, never by printing values.
- **`E:\test\my_reporter-main` has a `.env` in the repository root — confirmed safe.**
  Verified 2026-09-29: listed in `.gitignore` (line 13), `git log --all -- .env` returns
  nothing, `git ls-files` does not track it, and the working tree is clean. The file is
  live but has never been committed.
- **Do not translate a query before passing it to either database.** Both search exact
  Burmese wording; the existing project rule applies unchanged.
- **`fetch_independent_news.py` reaches The Irrawaddy through its Telegram mirror to get
  past a Cloudflare 403.** That is a deliberate choice already made in that project. If
  JARVIS ever reads the same articles, it reads them from the database — it should not
  re-implement the bypass.

---

## 7. One-line summary

The two systems are not competitors and not duplicates: **JARVIS reads three outlets from
one database, my_reporter reads four from another, and the overlap is only BBC Burmese and
The Irrawaddy.** The cheapest real gain is not a new system — it is pointing JARVIS's
existing tools at the second database, starting with the 376 verified fuel and gold prices
that JARVIS has no way to know today.

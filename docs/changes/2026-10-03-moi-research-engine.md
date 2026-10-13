# Change review — the MOI research engine: a local index, crawled daily, with the live site as fallback

| | |
|---|---|
| **Date** | 2026-10-03 |
| **Author** | assistant |
| **Reviewer** | self-review + `review_gate.py` (a second reader on Axis D is still owed) |
| **Owner sign-off** | **not required** — no S0/S1 finding stands unfixed; see §5 |
| **Severity of the change** | **S2** — additive; no existing path answers differently |

---

## 1. Intent

**What the owner asked for**, in his own words:

> *"MOI website ကို မေးတိုင်း live website တစ်ခုလုံး crawl မလုပ်သင့်ပါဘူး … background crawler
> နေ့တိုင်း ဥပမာ 11:30 AM … New articles only → Extract → Database. … ပြီးရင် JARVIS က Database
> Search → Relevant articles → Gemini → Answer … Database မှာ မတွေ့ရင် → Live MOI Search."*

**What changes.** Two new files and a new tool:

- `core/moi_index.py` — a SQLite store of MOI articles in the owner's own column list, plus the crawler
  that fills it and the extraction that labels each row.
- `actions/moi_research.py` — the `moi_research` tool: **index first, live site as the fallback**, plus
  `update`, `status`, `numbers`, `entities` and `schedule`.

**What is different for the owner.** A keyword question — *"ရွှေဈေးနဲ့ပတ်သက်တဲ့သတင်းတွေ
ရှာပေး"*, *"ဦးမင်းအောင်လှိုင်ကို mention လုပ်ထားတဲ့ သတင်းတွေ"*, *"ဒီသတင်းထဲက ကိန်းဂဏန်းတွေ
သီးသန့်ပြောပြ"* — is answered from one local query instead of up to twenty requests to a government
site, and it reaches the whole archive rather than only the pages a section walk can cover. The crawl runs
unattended at 11:30.

**What this deliberately does NOT do.** It does not change `moi_news`, which keeps answering *section +
date window* questions live. It does not touch Supabase, the PDF pipeline, or the newsroom. It does not
replace the 2026-10-01 rule — see §2.

---

## 2. The relationship to the 2026-10-01 rule — stated, not assumed

That rule is **"Never reach for the DB first on a state-news question — it answers from a copy."** This
change reads a database, so the first job was to work out whether it overturns the rule. It does not, and
the distinction is written into `core/moi_index.py` and `MEMORY.md` rather than left for someone to
re-derive:

| | the copy the 2026-10-01 rule banned | this index |
|---|---|---|
| where it came from | migrated state-paper PDFs | a crawl of **the same site** |
| freshness | unbounded, and was months old | stamped `created_at` / `last_run`; `status()` reports the date range |
| when it is used | always, first | first for a **search**; never for a section + today question |
| what happens when it misses | answered from the copy | falls back to **live `moi.gov.mm`**, and says which source it used |

The tool description of `moi_news` states the division both ways, so the model cannot resolve it by
reading one file.

---

## 3. Files touched

| File | What changed |
|---|---|
| `core/moi_index.py` | **new** — schema, extraction (`locations_in`, `organizations_in`, `numbers_in`, `keywords_in`, `extract`), `search` / `by_entity` / `get`, `new_cards` / `crawl` / `status` |
| `actions/moi_research.py` | **new** — the `moi_research` TOOL, the seven actions, `schedule_crawl`, `--scheduled` |
| `core/moi_client.py` | `article_page()` added: **one** fetch shared by `article`, `article_state`, `article_meta`, `article_date` (was four); `_page_meta()` holds the date/author parse |
| `actions/moi_news.py` | description only — names `moi_research` as the tool for a keyword/name/number question |
| `check_moi_index.py` | **new** — 153 offline checks, no network |
| `review_gate.py` | `check_moi_index.py` added to `SUITES_FAST` |
| `.workbuddy-ai/memory/MEMORY.md` | the sources table, the rule exception, the tool count, the verification list |

**New files:** `core/moi_index.py`, `actions/moi_research.py`, `check_moi_index.py`,
`docs/changes/2026-10-03-moi-research-engine.md`. **Deleted:** none. No new dependency — SQLite is
stdlib.

---

## 4. The five axes

### A — Silence: *does this change fail loudly?*

The whole change is about one failure mode: **an empty answer standing in for a failure.**

| situation | what is said |
|---|---|
| crawl could not reach the site | `reachable: False` + the reason; the table is untouched; `action='update'` says `မချိတ်နိုင်ပါ` |
| an article would not read | recorded in `errors`, the rest of the section is still stored |
| the index has nothing | "index missed" **then** a live search — two different sentences |
| the live site also has nothing | `မတွေ့ပါ` |
| an undated row was filtered out | counted in `undated_skipped`, and the answer says so |

`crawl()` **never raises**; `_scheduled_run()` exits **2** when unreachable so Task Scheduler shows it.

### B — Honesty: *finding, limitation, or failure?*

The four sentences are the same four `moi_news` uses, spelled out in this tool's description — and the
project's own lesson ("a tool result must name the exact sentence") is why they are in the *result*, not
just in prose: `_do_search` writes `မချိတ်နိုင်ပါ` **and** says *"`မတွေ့ပါ` မဟုတ်ပါ"* when the
socket is the problem.

`author` is `""` in most rows and that is the honest answer: a state news page carries no byline, only
Drupal's `Submitted by moiuser4`, a **machine account**. Storing it would be a fabricated attribution.

### C — Trust: *where did this come from?*

Every answer names its source — `📇 MOI index` with the crawl date, or `🌐 live moi.gov.mm` — and every
row carries its `section`, `published_date` and link. Extraction is a glossary plus the project's own
`entities` module: **a malformed stretch of Burmese cannot produce a person or a place that does not
exist.**

### D — The model-facing surface: *what does the tool description steer?*

This is where the change is most exposed, because a tool description steers harder than the code does.

- Both descriptions name each other, so neither wins by not being mentioned.
- `moi_research` names `moi_news` / `news_section` / `reporter_news` / `reporter_prices` / `news_search`
  as **NOT** it; `moi_news` now names `moi_research`.
- **Still owed:** a second reader on this axis. It is exactly where the 2026-10-01 addendum's worst
  findings lived, and the author is the person who wrote both descriptions.

### E — Evidence: *how do we know?*

`py check_moi_index.py` — **153 checks, offline, no network.** `review_gate.py` — **0 failures**. The
index and the crawler were exercised against a temp database with `moi_client` stubbed, so `crawl`,
"new articles only", the unreachable path and the dispatcher path are all real runs rather than
assertions about intent.

---

## 5. Findings (self-review)

Every one was found by running the thing, and each is fixed and checked.

| # | Sev | Defect | Fix |
|---|---|---|---|
| 1 | **S1** | `upsert` bound Python lists to TEXT columns → `ProgrammingError: type 'list' is not supported`, failing the **whole insert** — the index silently never filled | serialise the list columns in `upsert`; asserted |
| 2 | **S1** | the name search returned **0** for an article that named the person: `people` is stored as separate `honorific` / `name` fields, so `ဦးအောင်ကြိမ်` is never a contiguous substring of the cell | match labels in Python against the printed form; asserted |
| 3 | **S1** | `ပြည်` (the city) matched inside `ပြည်ထောင်စုဝန်ကြီး` — a ministry became a **location** | a place of ≤ 5 chars must stand alone (token or token + particle); asserted both ways |
| 4 | S2 | the papers print `ကုန်သွယ်ရေးဝန်ကြီးဌာန`; the glossary holds the long form → **0 organisations** | a second glossary `MINISTRY_SHORT`; a regex was tried and rejected (it glued the clause in front of it) |
| 5 | S2 | an unescaped `%` in a query matches everything — a silent over-answer | `_like()` escapes LIKE's own wildcards; asserted |
| 6 | S2 | `make_row` did not set `updated_at`, so the row was not every declared column | set it; asserted |
| 7 | S2 | the test file defined `main()` and never called it → **exit 0 with no output**, a suite that looks green because it did not run | entry point added |

**Disposition:** all resolved in place, all verified by `check_moi_index.py`.

---

## 6. Gate

```
review_gate.py             →  0 failure(s)
check_moi_index.py         →  153 checks, all pass
check_moi.py               →  96 checks, all pass
check_entities / check_topic / check_sections  →  pass
```

**The `moi_client` refactor is the one change to an existing, heavily-tested file.** `article()` could
return `""` on an unreachable page where it previously raised — an improvement on the voice path (a
network fault can no longer crash a turn), and `moi_news` guards the call with `available()` and reads
`article_state()` first, so nothing it does changed.

---

## 7. What happens next

1. **A live voice session** is still the top of the list, and it is now more valuable: two descriptions
   steer one router, and only a real turn shows which one won.
2. **Seed the index.** Run `python actions/moi_research.py --update` once with the VPN up (or wait for the
   11:30 task) — the index is empty until then, and every question falls back to live until it is not.
3. **`moi_news` and `moi_research` both claim state news.** If a live run shows the model picking
   wrongly, the fix is one sentence in one description — not new code.
4. **The newspaper PDFs are not crawled yet.** The owner named them as the next step; the column set is
   ready for them (`section` / `published_date` / `content`).

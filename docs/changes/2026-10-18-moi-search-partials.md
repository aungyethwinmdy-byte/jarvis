# Change review — the gem-emporium miss: compound queries were never reduced, and the index could go stale silently

| | |
|---|---|
| **Date** | 2026-10-18 |
| **Author** | assistant |
| **Reviewer** | `check_moi_index.py` + live re-verification of the owner's exact question |
| **Owner sign-off** | **not required** — no S0/S1 finding stands unfixed; see §5 |
| **Severity of the change** | **S2** — two additive fallbacks + a background refresh; no existing answer changes shape |

---

## 1. The failure the owner saw, in order

> *"ကျောက်မျက်ပြပွဲက ဘယ်လိုအခြေအနေရှိလဲ" → "နောက်ဆုံးရက် ၃၀ အတွင်း … ရှာမတွေ့ပါ"*

Three independent defects, each measured live on 2026-10-18 before anything was coded:

| # | Defect | Measured evidence |
|---|---|---|
| 1 | **A Burmese compound is never reduced.** Both the index and its token fallback split queries on **spaces** only. The owner's `ကျောက်မျက်ပြပွဲ` is one word; the site spells the event **`မြန်မာ့ကျောက်မျက်ရတနာပြပွဲ`** — `ရတနာ` rides inside the site's name — so the query is not a substring of anything. `ix.search` → **0**, site search → **0**. | `python _tmp_probe_search.py`: `'ကျောက်မျက်ပြပွဲ'` = 0 everywhere; `'ကျောက်မျက်'` → 6 index rows incl. **`/news/88737`** (the 61st Emporium, Oct 8→17) and the live section walk → **`/news/89483`, `/news/89446`** — the exact article open in the owner's browser. |
| 2 | **The index went 12 days stale with no signal.** Last successful crawl `2026-10-06`; newest indexed article `2026-10-05`. The scheduled task `JARVIS_MOI_Crawler` shows `Last Result: -1073741510` (process killed mid-run) on a task that "ran" daily — every killed run before the per-run flush lost **all** finished sections. All Oct 6–17 emporium articles were invisible to the index. | `moi_index_meta`: `last_run 2026-10-06T13:04`, `last_attempt 2026-10-14 unreachable`; `schtasks /Query /V`. |
| 3 | **A subject question was answered by a list.** The model called `moi_news` with `{'action':'list','section':'ပြည်တွင်းသတင်း','days':7}` — **no `query`** — the tool showed the first 8 of 169 unrelated cards, and the owner was told "no gemstone news". | The turn log: `🔧 moi_news {'action': 'list', 'section': 'ပြည်တွင်းသတင်း', 'days': 7}`. |

---

## 2. What changed

### `core/moi_index.py`

* **`partials()`** — sub-phrases of a query, cut at **Burmese syllable clusters** (`_syllable_starts`), longest-then-leftmost, full query excluded, `min_len` 5, capped 10. `<5` queries return nothing, untouched. `_search()` now runs `full → token-AND → partials`, and `matched` names the phrase that finally hit (the `undated_skipped` count searched the *matched* phrase, not the original, so report and shown list agree).
* **`crawl()` commits per section, not once at the end.** A killed run keeps every section it finished. This is the direct repair for how the scheduled task has been dying.
* **`is_stale()` / `catchup_if_stale()`** — when the newest indexed article is > `max_age_days` (2) behind Yangon today and the site is reachable, a bounded `crawl()` starts on a **daemon thread**; an event + lock guard double-spawns; a `last_catchup` meta gate means a 4-hour window between refires. Search storms cannot spawn crawl storms either way, and killing the host process costs at most the section being fetched (per-section commits).

### `actions/moi_news.py`

* The live search gains the same reduction: after the site search and the whitespace-token try, **`ix.partials()` candidates** (capped `_PARTIAL_TRIES=4`, one request each) are tried; `term` becomes the phrase that worked so the answer says what it searched.
* The catch-up note (`_CATCHUP_NOTE`) is appended when the live fallback answered **or** the index answered while the copy is days behind — the refresh is started in the background at the same moment.
* **`_LIST_SEARCH_HINT`**: a section window with more than 24 cards (e.g. `/other-news`, 7 days) now says so — *"သတင်း N ခု ရှိပါတယ် … action='search' + query နဲ့ ရှာပါ"* — because a list cannot see a subject past the first `limit` cards.
* **Tool description**: a subject-named question (`'ပြည်တွင်းသတင်းမှာ ကျောက်မျက်ပြပွဲနဲ့ပတ်သက်တဲ့ သတင်းပါလား'`) **must** be `action='search'` + `query`, never `list`; the 2026-10-18 case is spelled out. The `query` parameter documents that a single compound is fine and self-reduces.

### `actions/moi_research.py`

* Same partial reduction before giving the live "မတွေ့", same catch-up note; description adds that a days-stale index refreshes itself at search time (no pre-`update` needed).

### `check_moi_index.py`

* New regression block in `_search`: seeded row titled `…မြန်မာ့ကျောက်မျက်ရတနာပြပွဲကို…`, asserts `partials`' cut order, a short query's no-op, and `search("ကျောက်မျက်ပြပွဲ")` → **1 hit, `matched == 'ကျောက်မျက်'`**. The seed deliberately keeps the compound out of the summary — the first version of the seed made the full phrase match and would have passed with the fallback dead (caught by the suite).

---

## 3. Why syllable cuts, and what they cannot do

Burmese writes a syllable as one unbroken cluster; every word boundary is a cluster boundary, but not every cluster boundary is a word boundary. The splitter is therefore an *over-split* (it may cut `ရတနာ` as `ရ|တ|နာ`), and the fallback can afford that: a wrong cut only produces a candidate that matches nothing and falls through — it cannot produce a wrong article. What it cannot do is bridge two separate words (`ကျောက်` + `မျက်` with a word between is bridged; two unrelated words are not) — the whitespace AND-path still owns that case.

---

## 4. Honesty invariants kept

* `matched` still says what was actually searched; the catch-up answer is labelled live/index the same way.
* The catch-up note is an *information* note inside the untrusted wrapper (same class as `_SEARCH_SCOPE`), not a command.
* `is_stale()` treats an empty index and an unparsable newest date as *not stale* — a limitation must not fire a crawler after a date it cannot read.
* The scheduled task, `update` action and this auto-catch-up are three paths to the same bounded `crawl()` — none new to the table's schema.

---

## 5. Gate

```
check_moi_index.py   →  all checks pass (110 + new 6)
check_moi.py         →  all checks pass
check_moi_voice.py   →  0 failures
one-time catch-up    →  other-news pages=26 (26-page walk ≈ 12-day gap) then all sections pages=6
owner's question     →  moi_research search 'ကျောက်မျက်ပြပွဲ days=30' → emporium articles, dated, named
```

---

## 6. What happens next

1. **The `-1073741510` task deaths are not fixed at the root** - the machine's state at 11:30 booked it (sleep, reboot mid-run). The per-section commits + the search-time catch-up now make those deaths survivable instead of catastrophic; if they keep happening, look at Run As / "Start the task only on AC power" in Task Scheduler.
2. The other five-day topics (PPIB/newsroom) were untouched - the emporium story is state-media, so this index is the right place.

---

## 7. The two database searches missed the emporium the same way — same repair, same day

The owner then asked the database side ("database မှာ သတင်းရှာတာ မတွေ့ဘူး") and
both Supabase search systems measured exactly the failure the MOI tools had:

* State papers (`reporter_news`): `search_count('ကျောက်မျက်ပြပွဲ')` = **1**
  (the Sep 13 preview row) while `search_count('ကျောက်မျက်')` = **53** — the
  papers title the event `မြန်မာ့ကျောက်မျက်ရတနာပြပွဲ`, exactly like the site.
* Newsroom archive (`newsroom_search`): `search_articles('ကျောက်မျက်')` finds
  PPIB's emporium stories (Oct 8–12); the compound finds **0**.

### `core/burmese.py` (new)

* The syllable cutter **moved here** from `moi_index` — it is a language rule,
  not an index rule, and three systems now need it. `moi_index.partials` is
  re-exported (with a pointer comment), so earlier callers and
  `check_moi_index.py` keep reading the same name.

### `actions/reporter_news.py`

* **`_count_reduced(term, days) -> (n, reduced, thin_hint)`** — three shapes:
  plain count; 0-compound → best sub-phrase **swaps in and the answer names
  it**; a compound that counts something thin on its own (1–3) **keeps the
  exact count** and carries a pointer line with the stem's larger count
  (≥ 8 and ≥ 4×n) — a swap would drown a genuinely rare exact topic.
* `search`, `day`, `byday`, `timeline` all reduce now; `date_range_for` runs
  on the phrase that counted. **Best rows, not first rows**: an over-split
  fragment also matches the rows that spell the compound verbatim (it was cut
  from that form), so candidate scans keep the largest listing and stop at
  **4** (rows or count) instead of taking the first nonzero.
* `timeline`'s pointer is skipped when the listing was truncated at a small
  `limit` — a truncated listing is not a rare topic.
* Descriptions: pass ONE or TWO words, never the sentence; a compound is fine,
  it reduces itself and the answer names the phrase it used.

### `actions/newsroom_search.py`

* Same reduction before "မတွေ့ပါ" (cap 3), note line prepended; description
  updated with the compound sentence.

### `actions/moi_news.py` / `actions/moi_research.py`

* Their live compound loops upgraded from first-hit-wins to the same
  best-of/break-at-4 rule (an over-split fragment of the compound can match
  the few site results that spell the compound verbatim — first hit would
  stop at the preview).

### Gate

```
check_entities / check_topic / check_sections / check_moi / check_moi_index
check_newsroom, check_moi_index (moi-index regression re-run after the move)
reductions verified OFFLINE against a stubbed client: thin-hint stays honest,
the 0-swap picks the stem (53) over the fragment (1), absent stays absent,
a big exact count fires no extra query
live (network up): search 'ကျောက်မျက်ပြပွဲ' days=7 → 19 hits Oct 12–18;
newsroom 4 hits — both naming 'ကျောက်မျက်'
```

(Supabase went unreachable from this machine later that day — Cloudflare-edge
connect timeouts on both projects, checks via `supabase.co` apex still pass —
so the live re-verify above stands on the earlier window. The tools answer
"ခဏနေ ပြန်မေးပါ" honestly meanwhile.)

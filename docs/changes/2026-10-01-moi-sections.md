# Change review — answer every state-news question from moi.gov.mm, by section

| | |
|---|---|
| **Date** | 2026-10-01 |
| **Author** | assistant |
| **Reviewer** | self-review + `review_gate.py` (see §4 — a second reader on Axis B and D is still owed) |
| **Owner sign-off** | **required** — three S1 findings were fixed in place; see §6 |
| **Severity of the change** | **S1** (a section with news was answered as "not found") |

**This is the first change reviewed under `docs/CODE-REVIEW.md`.** The mechanism was written the same
day and had not been used; everything below is the first real exercise of it, including the two places it
was awkward.

---

## 1. Intent

**What changes.** `moi_news` / `core/moi_client.py` now read **all eleven sections** the Ministry of
Information's site actually serves, in **three** card layouts instead of one, and answer a "today"
question with the site's own date window. The owner can ask *"ဒီနေ့ နိုင်ငံတော်သမ္မတ သတင်းရှိလား"* and
get the section, or an honest "none today" with the nearest story named.

**What is different for the owner.** Before this change, three of the eleven sections were unreachable and
one of them — ပြည်တွင်းသတင်း — was **answered as "no such news" on a day it carried news**. Two whole
sections (ဆောင်းပါး, အယ်ဒီတာ့အာဘော်) were invisible, and every ဆောင်းပါး article read as empty.

**What this deliberately does NOT do.** It does not touch `jarvis_news` (the owner's stored material), the
Supabase tables, or the PDF pipeline. It does not add the announcement/law/video sections — those list
items but carry no article cards, and the owner asked for *news*.

---

## 2. Files touched

| File | What changed |
|---|---|
| `core/moi_client.py` | `SECTIONS` 7 → 11 with the publisher's own labels; `other-news` relabelled; two card patterns + a `_LAYOUT_B` set; a **balanced** `_div_inner`; `article()` tries two containers; new `section_exists()`; aliases extended with the ordering that matters |
| `actions/moi_news.py` | `days` parameter (Yangon-time window); the four-answer honesty rule; `_section_missing()` names the real sections; bounded search with an honest coverage note; the `isdigit` trap closed; description rewritten (Axis D) |
| `check_moi.py` | **new** — 50 offline checks, one per defect below |
| `review_gate.py` | `check_moi.py` added to `SUITES_FAST` |
| `.workbuddy-ai/memory/*` | `RULES.md` (new rule), `MEMORY.md` (index), `RULES.md` ingest note, `2026-10-01.md` Round 23 |

**New files:** `check_moi.py`, `docs/changes/2026-10-01-moi-sections.md`
**Deleted files:** none. Six `_recon_*.py` probe scripts were written and removed in the same session.

---

## 3. The five axes

### A — Silence: *does this change fail loudly?*

The whole change is about this axis. `list_section()` returns `[]` both when a section is empty **and**
when the fetch failed — a failed read and an empty source are indistinguishable at that return. The
action compensates with two probes (`available()`, and the new `section_exists()`) and produces **four
distinct sentences** rather than two:

| situation | sentence |
|---|---|
| found | the article, with source, section, date, link |
| the section has news, none in this window | `မရှိပါ` + the nearest story named |
| the section exists and is empty | `မတွေ့ပါ` |
| the site could not be reached | `မချိတ်နိုင်ပါ` |
| the section slug does not exist | names the ten real sections |

`_div_inner` replaces a lazy regex; a lazy match loses content silently, which is the axis-A failure mode.

### B — Honesty: *finding, limitation, or failure?*

- The limitation is the **first sentence** of the not-in-window answer, and the pointer is second —
  because the first sentence is the one the model speaks. Asserted by a check.
- The **search coverage claim was a lie** and is now bounded: the old code walked 20 pages × 7 sections
  and then said *"searched the site"*. It now walks 4 pages per section and **says so**
  (`_SEARCH_SCOPE`), because a bounded search cannot make an unbounded claim.
- `_card()` no longer prints a summary that is just the headline again — measured on `/news/88750`, whose
  body is empty so its summary *is* its headline. Printing it twice looked like a summary that said
  nothing, which it was.

### C — Trust: *is model output untrusted, and is anything irreversible gated?*

Nothing irreversible. No new outbound call, no write, no delete, no `shell=True`, no path. The change only
reads a public website. `review_gate.py` G5/G7 are unchanged and green.

### D — The model-facing surface: *do the descriptions and parameters steer correctly?*

This axis was load-bearing and is where the earlier round's defect lived.

- The description now **names all ten sections in Burmese**, because *"a tool description steers the model
  harder than the code steers it"* — the model cannot pass a section name it has not been shown.
- A new `days` parameter exists **because the model cannot be relied on to compute a date**. The owner says
  "today"; the model passes `days=1`; the tool resolves Yangon time. The description says explicitly not to
  compute the date.
- The description states the four answer shapes and says **never to turn a failure or a limitation into
  "there is no such news"**.
- The unknown-section answer names the ten real sections instead of a generic refusal.

### E — Evidence: *is the claim measured, and read back?*

Every claim below is a live read of the site on 2026-10-01, not a reading of the code:

- the eleven sections and their labels — read from each page's own `<title>`
- card counts per section (20/20/20/20/20/20/20/20/10/10/20)
- `/amyotha-hluttaw-news` (the site's **own nav spelling**) returns **0 bytes**; `/amyotha-htuttaw-news`
  returns 20 cards — both measured
- `article()` before/after: `/article/88687` 0 → 7,282 chars; `/news/88603` unchanged at 9,023
- the owner's own question, end to end, through `_call_handler`

**Not verified:** the eleven sections were read one page deep for the count and up to 20 pages for the
listing; the archive depth of the new sections (how far back `/articles` and `/perspective` go) was not
measured. The `search` bound of 4 pages was chosen for latency, not measured for recall.

---

## 4. Gate

```
$ py review_gate.py
0 failure(s), 12 warning(s).
  [ ok ] S  check_entities.py passed in 1s
  [ ok ] S  check_topic.py    passed in 1s
  [ ok ] S  check_sections.py passed in 13s
  [ ok ] S  check_moi.py      passed in 1s
```

| Check | Where | Verdict |
|---|---|---|
| G6 | `check_moi.py:200` | **Reviewed — safe, and deliberate.** The line is `check('"၈၈၆၇၃".isdigit() is True', "၈၈၆၇၃".isdigit(), True)` — a test asserting the hazard *exists*, which is the point of the check. Not a defect. |
| G5 ×6, G6 ×1, G8 ×3 | unchanged from the previous review | All reviewed 2026-10-01; verdicts in `docs/STATUS-2026-10-01.md` §2. None touched by this change. |
| G9 | — | Was 6 stale `.pyc`; cleared in this session (25 files). Now green. |

**Gate gaps found by using it.** Two, and both are the gate being honest about its limits:

1. **G1 (compile) does not catch a `NameError`.** The `re` import was missing and the module compiled
   perfectly; the failure was a crash in one branch. `check_moi.py` now covers it.
2. **G6 flagged the comment explaining the `isdigit` trap**, in `moi_news.py`, before the fix. That was
   correct behaviour (a WARN is a review trigger), but it is the second time a text-level read produced a
   false positive. G6 is AST-based so it did *not* fire on the comment — the warning came from the
   `.isdigit()` call that was genuinely there. The `check_moi.py` hit **is** text-level, in the new suite,
   and is recorded above rather than suppressed.

---

## 5. Findings

### Finding 1 — S1 — a section with news dated today was answered as "not found"

- **Evidence.** `_CARD` required `href="(/news/(\d+))"` and exactly `class="card-text"`. `/other-news` and
  `/news` serve `href="/index.php/news/88749"` and `class="card-text text-justify"`. Measured:
  `len(_CARD.finditer(page))` = **0** for both, against **20** `/news/N` links on the page.
- **Mechanism.** `list_section("other-news")` → `[]` → `_cached` stores `[]` → the action sees no cards,
  `available()` is True, and it returns `_NOT_FOUND` — *"no such news"*. The section held articles dated
  **2026-10-01**, the day of the question.
- **Root cause.** One regex written against one section's markup, applied to all of them. The site has
  three layouts.
- **Confidence.** 0.98 — reproduced by counting cards with both patterns on the live page.
- **Fix.** `_CARD_A` accepts an optional `/index.php` prefix and `class="card-text[^"]*"`.
- **Verification.** `check_moi.py` asserts both forms parse; live, `other-news` returns 20 cards.

### Finding 2 — S1 — two sections were invisible

- **Evidence.** `/articles` (ဆောင်းပါး) and `/perspective` (အယ်ဒီတာ့အာဘော်) return **0** cards under layout
  A; both use `news-page`/`news-wrapper`. An earlier note in the project concluded the site had **no**
  section for these topics. It does.
- **Mechanism.** Not a wrong answer — the sections could not be named at all, so the owner could never ask.
- **Root cause.** The section list was built from one nav read and never re-measured.
- **Confidence.** 0.97.
- **Fix.** `_CARD_B` + `_LAYOUT_B`, and both sections added to `SECTIONS`.
- **Verification.** Live: 10 cards each, dated to 2026-10-01.

### Finding 3 — S1 — every ဆောင်းပါး article read as empty

- **Evidence.** `article()` used only `post-body`. Measured: `/article/88687` has **0** occurrences of
  `post-body`; its text is in the `field--name-body` div carrying `property="schema:text"`. Returned
  **0 chars**; the tool then told the owner the site had no text for the story.
- **Mechanism.** A missing container is indistinguishable from an empty article at that return value.
- **Root cause.** One container assumed for two page types.
- **Confidence.** 0.95.
- **Fix.** `article()` tries `post-body`, then the `schema:text` div, using the new balanced `_div_inner`.
- **Verification.** Live: `/article/88687` 0 → 7,282 chars; `/article/88746` → 9,485. `/news/88603` is
  unchanged at 9,023, so the news path did not regress.

### Finding 4 — S2 — the section label was a guess

- **Evidence.** The code said `other-news` → `အခြားသတင်း`; the page's own `<title>` says **ပြည်တွင်းသတင်း**.
- **Mechanism.** The model is told to pass what the owner said; a wrong label in the description teaches
  the model a name the owner never uses, and the section becomes unreachable by its real name.
- **Root cause.** A label written from inference rather than read from the source.
- **Confidence.** 0.99 — read from `<title>` on the live page.
- **Fix.** All eleven labels are now the publisher's own, read from each page.
- **Verification.** `check_moi.py` asserts `SECTION_LABEL["other-news"] == "ပြည်တွင်းသတင်း"`.

### Finding 5 — S2 — the search could not finish inside a voice turn

- **Evidence.** `search(pages=20)` across 7 sections is up to ~140 requests with a 0.3 s politeness pause.
  Measured during this session: the first attempt was **killed by the caller** before it answered
  (exit `SIGTERM`, no output) — and with 10 sections it is ~200 requests.
- **Mechanism.** A voice turn that never returns is a silent failure from the owner's side.
- **Root cause.** A batch-shaped walk used on an interactive path.
- **Confidence.** 0.9 — the timeout is reproduced; the exact page count varies with how fast each section
  runs out of pages.
- **Fix.** `_SEARCH_PAGES = 4`, and the answer **states the bound** rather than claiming the site was
  searched.
- **Verification.** `check_moi.py` asserts the cap and that the scope sentence is present.

### Finding 6 — S1 — a `NameError` in a branch no earlier test reached

- **Evidence.** `re.fullmatch` used in the `story` branch; `re` was never imported in `actions/moi_news.py`.
  Found by calling that branch, not by reading it.
- **Mechanism.** `re` is imported by the *client*, so the module compiled and every other branch worked.
  Only `action='story'` with a numeric id crashed — with a traceback the voice path would swallow.
- **Root cause.** The same shape as the project's recorded `_reporter_common.py` defect: a helper used in a
  branch that no check exercised.
- **Confidence.** 1.0 — a reproduced traceback.
- **Fix.** `import re`.
- **Verification.** `check_moi.py` asserts the import exists; the branch is exercised.

### Finding 7 — S3 — a Burmese-digit id built a bad URL

- **Evidence.** `"၈၈၆၇၃".isdigit()` is **True**, so `term.isdigit()` built `/news/၈၈၆၇၃`.
- **Fix.** `re.fullmatch(r"[0-9]+", term)`; the Burmese form is refused with a sentence asking for the id.
- **Verification.** `check_moi.py` asserts the trap is real and that the new test refuses it.

### Finding 8 — S3 — a summary that was the headline again

- **Evidence.** `/news/88750`'s body is empty, so its summary **is** its headline; `_card()` printed it
  under **အနှစ်ချုပ်** as if it were a summary.
- **Fix.** Skip the summary when it equals the headline.
- **Verification.** live: `/news/88750` now prints source, section, headline, link.

### Finding 9 — S3 — a doubled word

- **Evidence.** `_date()` already returns "… ရက်", and the sentence appended " ရက်နေ့က" → "… ရက် ရက်နေ့က".
- **Fix.** Dropped the suffix.

---

## 6. Disposition

**Changes required → resolved.** All nine findings were fixed in this change; none is waived. Three are
S1 and touch how the owner is answered, so the owner should read §5 and confirm the wording is what he
wants spoken — particularly the not-in-window sentence, which is the one he specified.

**Conditions:**

- The eleven sections were verified **one page deep** for counts. Archive depth for `/articles` and
  `/perspective` is unmeasured; the answers do not claim a depth, so nothing is currently misstated, but
  the claim cannot be made until it is measured.
- The search bound (4 pages/section) is a latency choice, not a measured recall bound. The answer now says
  so.
- **A second reader is owed on Axis B and Axis D** — the author reviewed his own change, which the process
  names as its weakest configuration.

**Follow-ups filed:**

| Follow-up | Owner |
|---|---|
| Add the announcement / law / video sections if the owner wants them (they list items but no article cards) | owner to decide |
| Measure archive depth per section, and state it in the answer | next change |
| Decide whether `search` should widen when the bounded walk finds nothing | owner to decide |

---

## 7. Memory note

- [x] A note appended to `.workbuddy-ai/memory/2026-10-01.md` (Round 23)
- [x] New rules added to `.workbuddy-ai/memory/RULES.md` and indexed from `MEMORY.md`
- [x] `py review_gate.py --static` shows `G10` green (memory files within budget)

---

## 8. Addendum — the live test, added after this record was written

The owner asked for a live test of *"မနေ့က ဒုတိယသမ္မတ သတင်းတွေရှိလား"*. It ran five times
(`probe_moi_live.py`, the real `_build_config()` + the real `_execute_tool`, no microphone). **The first
three runs each failed differently, and every failure was a defect no static review could see** — which is
the project's standing finding that four defects once survived 430/430 handler checks.

### Finding 10 — S0 — the state-news question was answered by the DATABASE tool

- **Evidence.** Run 2 of the same question: `news_section {'days': 2, 'section': 'ဒုတိယသမ္မတများ'}`. That
  tool reads the database copy, and it returned *"သတင်းစာ ထဲမှာ မတွေ့ရပါ"* plus a hollow-paper warning —
  the exact failure round 21 replaced. Run 1 had chosen `moi_news` correctly.
- **Mechanism.** `news_section`'s description was written in round 12 and **names this very question as its
  own case**: *"Use this whenever the question names one of the eleven sections … **including the `ရှိလား`
  form**"*, with `'မနေ့က ဒုတိယသမ္မတတွေရဲ့ သတင်းရှိလား'` as the worked example. Round 21's system change was
  written into `moi_news` and `jarvis_news` and **never into `news_section`** — the one tool that owns
  "section questions". So it competed, and its example was more specific.
- **Root cause.** A system change applied to two of the three tools that share a decision.
- **Confidence.** 0.97 — reproduced, and the cause is visible in the two descriptions side by side.
- **Fix.** `news_section`'s description now opens by redirecting state news to `moi_news` and says why (the
  copy is incomplete, measured: 0 readable rows for that day). `moi_news`'s description keeps the steering
  and names `news_section` explicitly as not-the-tool.
- **Verification.** Runs 4 and 5: `moi_news` chosen, **one** call, correct section, `days=2`.

**This finding also overturns a fix I had just made.** Run 1's only fault was a follow-up call to a
misspelled `yarvis_news`, and I "fixed" it by removing the competitor names from the description. That
produced run 2 — a **worse** failure. The lesson is the project's own: *a tool description steers the model
harder than the code steers it*, and **a competitor that is not named will win.** The check I wrote to
protect that fix asserted the opposite of the truth and was rewritten.

### Finding 11 — S1 — the dispatcher answered an invented tool name with a dead end

- **Evidence.** Run 1: `yarvis_news` (a misspelling of `jarvis_news`, a name the model had only seen in a
  description telling it *not* to use that tool) → `"Unknown tool: yarvis_news"`. The model called it a
  second time with the same spelling and wasted the turn.
- **Mechanism.** The fallback named no alternative and gave the model nothing to act on.
- **Fix.** `_closest_names()` ranks the declared tools by shared letters, so the reply becomes
  `Unknown tool: yarvis_news. Did you mean jarvis_news? Call only a declared tool, or answer with what you
  already have. Never invent a tool name.`
- **Verification.** `check_moi.py` asserts `_closest_names("yarvis_news", …) == ["jarvis_news"]`, that a
  random name yields no suggestion, and that the bare-string reply is gone.

### Finding 12 — S1 — the limitation was spoken as a finding

- **Evidence.** Run 4. The tool's first line was **`သတင်း မရှိပါ`** (there is none in this window). The model
  spoke **"မတွေ့ရပါဘူး"** (I did not find). The project's most-repeated rule, drifting one layer below the
  product — the layer no handler-level suite can see.
- **Mechanism.** The result told the model *what to report* but not *which sentence to use*.
- **Fix.** The not-in-window answer now names both sentences: say **`မရှိပါ`**, do not say `မတွေ့ပါ`, and
  says why (this is not a failed search, it is an empty window).
- **Verification.** Run 5: **"မနေ့ကနဲ့ ဒီနေ့ အတွက် ဒုတိယ သမ္မတ သတင်းတွေ မရှိပါဘူး"** — the right sentence,
  with the nearest story attached.

### The probe traps this run hit, and one new one

Two were already known and are handled: **`send_client_content` is accepted by the SDK and then rejected by
the server** with `1007 Request contains an invalid argument` during receive (the probe now tries
`send_realtime_input` first), and **a receive-loop exception must be printed** — the first version swallowed
it and reported "the model made no tool call at all" for a loop that had died.

One is new and is now in the probe: **`'moi_news' in str(cfg.tools)` is not a declaration check.** It
reported `moi_news declared: False` for a tool that was loaded and declared. Read
`function_declarations[].name`.

### Files added by the addendum

`probe_moi_live.py` (the reusable harness) · `main.py` (`_closest_names` + the unknown-tool reply) ·
`actions/news_section.py` (the redirect) · `actions/moi_news.py` (the two result instructions) ·
`check_moi.py` (65 checks, up from 50).

### Disposition of the addendum

**Changes required → resolved.** Findings 10–12 are fixed and verified by a live run. Finding 10 is **S0**:
it means a state-news question could be answered from the copy the whole change exists to bypass, and it
was found only because the owner asked for a live test.

**Still owed:** a second reader on Axis B and Axis D. Both of the addendum's worst findings are Axis D — a
description that steers — which is exactly where the process says a second reader earns the most, and where
the author (me) twice made it worse before making it better.


# Change review — remove `jarvis_news`; state news is the website only

| | |
|---|---|
| **Date** | 2026-10-01 |
| **Author** | assistant |
| **Reviewer** | self-review + `review_gate.py` |
| **Owner sign-off** | **given** — see §1, including the contradiction in the instruction and how it was resolved |
| **Severity of the change** | **S1** — two files removed with no version control; one coverage claim had to be verified before acting |

---

## 1. Intent

**What changes.** `actions/jarvis_news.py` and `core/jarvis_client.py` are removed. Nothing in the app reads
the `categorized_news` table any more. State news comes from `moi.gov.mm` via `moi_news`, which was already
the routing; this removes the alternative.

**The owner's instruction, and a contradiction in it.** Two questions were put; the answers disagreed:

| question | answer |
|---|---|
| what to do with the Supabase news tools | *"သတင်းဌာန … ကမ္ဘာ့သတင်း … ဒီစနစ်က သုံးမှာလေ၊ **jarvis news ကိုဖျက်လိုက်**၊ ကျန်တာ ထားထားလိုက်"* |
| the five topics the site lacks | *"**အဲဒါ ၂ ခု ချန်ထား**"* (keep `jarvis_news` + `reporter_prices`) |

**The conflict was resolved by measurement, not by guessing which answer to prefer.** `core/news_sections.py`
(the reporter project, which **stays**) already indexes exactly the five topics the website lacks —
verified in the source: `စီးပွားရေး` · `လူမှုရေး` · `ပညာရေး` · `ကျန်းမာရေး` · `သဘာဝဘေး`. And
`reporter_prices` covers fuel/gold. So **removing `jarvis_news` loses no coverage**, and both answers are
satisfied: the tool the owner named is gone, and the gap he wanted kept is still filled.

**What this deliberately does NOT do.** It does not touch `news_section`, `reporter_news`, `news_search`,
`reporter_prices`, the newsroom (PPIB / BBC Burmese / The Irrawaddy) or world news (Reuters / AP). It does
not drop any database table — the data is untouched, and the owner's "Supabase မသုံးတော့ဘူး" is read as
*stop answering news from it*, not *destroy it*. It does not touch the **reporter** project, which is what
the remaining tools read.

**A warning before acting.** The removal is irreversible — **there is no git repository** — so the two files
were copied to `backup/removed-2026-10-01/` **before** deletion, and the copy is asserted by a check.

---

## 2. Files touched

| File | What changed |
|---|---|
| `actions/jarvis_news.py` | **deleted** (copy at `backup/removed-2026-10-01/`) |
| `core/jarvis_client.py` | **deleted** (copy at `backup/removed-2026-10-01/`) |
| `check_agent.py` | the five checks that drove `jarvis_news._block()` removed with the code; a comment records where the file went |
| `check_moi.py` | +9 checks: the files are gone, the backup exists, `news_section` still covers the five topics, and no live file imports the removed modules. The `jarvis_news` competitor assertions and the `_closest_names` example updated |
| `actions/moi_news.py` | docstring + description: `jarvis_news` out of the competitor list, the five topics and the prices named as the one thing the site does not carry |
| `actions/news_section.py` | description now states it **owns** the five topics the site lacks, so those questions do not go to `moi_news` |
| `core/moi_client.py` | docstring: `jarvis_client` out, `reporter_client` in |

**Tools: 33 → 32.** Verified by the gate's `G2`.

---

## 3. The five axes

### A — Silence

The loader discovers `actions/*.py` by globbing `*.py`, so a deleted file simply stops existing as a tool —
that is loud in the log (`Action discovery complete: 32 active`). The risk here was the **reverse**: a
dangling `import jarvis_news` in `check_agent.py` would have failed at check time, not silently. It was
found by grepping every reference before deleting, and it is now asserted by AST.

### B — Honesty

The description now says which source owns which question **in both directions**: `moi_news` says the five
topics and the prices are *not here*, and `news_section` says they belong *here*. A one-sided redirect is
how `news_section` won the turn in the previous change (round 24, Finding 10).

### C — Trust

No new outbound call, no write, no delete inside the app, no secrets. The only irreversible act is the file
removal itself, and it is backed up.

### D — The model-facing surface

`moi_news`'s competitor list drops from three names to two. `news_section` gains the topics it owns. Both
directions are asserted by checks. **This axis is where the previous change's S0 lived**, so it was
re-verified with a live run rather than by reading (§4).

### E — Evidence

- **The coverage claim was measured, not assumed**: `core/news_sections.py` was read and the five topics
  confirmed present, and that is now a check. Had this not been verified, the removal would have silently
  dropped five topics.
- **The routing was re-verified live** after the removal, because the competitor set changed: one call,
  `moi_news {'action':'list','days':2,'section':'ဒုတိယသမ္မတ'}`, spoken with `မရှိပါဘူး`, 420,510 bytes.
- **Not verified:** that the owner wants the *table* left intact. He was asked what to do with the tools,
  not the data, and the data was left alone — recorded as an assumption, not a decision.

---

## 4. Gate

```
$ py review_gate.py
0 failure(s), 12 warning(s).
  [ ok ] G2  32 tools checked for shape, signature and description
  [ ok ] S   check_entities.py passed in 1s
  [ ok ] S   check_topic.py    passed in 1s
  [ ok ] S   check_sections.py passed in 10s
  [ ok ] S   check_moi.py      passed in 7s
```

### Finding 13 — S2 — my own check searched for a string and found itself

- **Evidence.** The first version of the dangling-import check was
  `"import jarvis_news" in p.read_text(...)`, run over every `.py` including `check_moi.py`. That file
  contains that literal string inside the check, so it **reported a defect that did not exist** and the gate
  went red for a clean tree.
- **Mechanism.** A substring test cannot distinguish code from the code that searches for it.
- **Root cause.** The same mistake the review gate itself made twice on 2026-10-01 — raw-text scanning. **A
  third instance of one defect class**, and it was written *by the same author, in the same session, hours
  after writing the rule against it.*
- **Fix.** `ast.parse` and walk for `Import` / `ImportFrom` nodes.
- **Verification.** The check now reports `[]` offenders.

**Worth recording as a process observation:** the standards document says *"Count, do not reason"* and the
gate's own docstring says *"read the syntax tree, not the text"*. The rule was written, then broken three
times in one day. A rule that is only in a document does not hold; the gate's G6 being AST-based is what
makes it hold for `isdigit`, and this check is now AST-based for the same reason.

---

## 5. Disposition

**Approved with conditions.**

- The owner's two answers conflicted; the resolution is recorded in §1 and rests on a measurement
  (`news_section` covers the five topics). **The owner should confirm that reading** — if he meant
  *keep `jarvis_news` itself*, the copy is at `backup/removed-2026-10-01/` and restoring it is one copy
  command.
- The `categorized_news` table and the reporter project's tables are **untouched**. If the intent was to
  stop storing, that is a separate decision not taken here.

**Follow-ups filed:**

| Follow-up | Owner |
|---|---|
| Confirm the table data should stay (nothing was dropped) | owner |
| Delete `backup/removed-2026-10-01/` once satisfied — or leave it as the only copy | owner |
| `check_agent.py` now has no coverage of the row-renderer Zawgyi guard; if a row-rendering tool is ever added back, that guard needs re-testing | next change |

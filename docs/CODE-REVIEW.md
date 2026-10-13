# Code review standards — Mark-LIV / JARVIS

**Status:** adopted 2026-10-01 · **Applies to:** every change to `main.py`, `core/`, `actions/`, the
`check_*.py` suites, `config/*.sql`, and any new tool · **Process:** `CODE-REVIEW-PROCESS.md` ·
**Record:** `CHANGE-REVIEW-TEMPLATE.md` · **Automated half:** `review_gate.py`

---

## 1. Why this document exists

The project's quality is inconsistent for one specific reason, and the history states it plainly:

- `AGENT-AUDIT.md` found **10 defects** (F1–F10). **None of them raised an exception.**
- Rounds 12–21 of the work log found **eight more**. Four were found *after* `check_agent.py` passed
  **430/430** — by running the real assistant once.
- `check_agent.py` itself has three times failed *because the data got better*, and twice failed for a
  reason that hid a real bug underneath it.

Every one of those is the same failure mode: **the code was wrong and nothing said so.** A handler swallowed
its argument dict. A loader skipped a broken tool file without a word. A gate declared glyph codes "usable
text". A search claimed to have checked a paper it never opened. A text filter muted the assistant's reply.

So this is not a style guide. It is a review standard organised around one question:

> **If this change is wrong, will anything say so?**

If the answer is no, the change is not ready — regardless of how good it looks.

### What this standard is not

It does not enforce formatting, naming, or file layout. The project has a consistent house style already;
`AGENT-AUDIT.md`'s F6 lesson — *"counting keywords is not evidence"* — applies to style too. A reviewer who
spends the review on naming has not done the review.

---

## 2. Severity

Severity describes the **consequence if the change ships wrong**, not how hard it is to fix.

| Level | Name | Definition | Required action |
|---|---|---|---|
| **S0** | Blocker | Corrupts stored data, loses the user's data, or acts irreversibly without a gate. Or: a change that makes a silent failure *more likely*. | Do not merge. Fix or abandon. |
| **S1** | Major | A silent wrong answer, a wrong spoken fact, a permanent bad entry in the user's memory, or an unguarded path off the machine. | Fix before merge, or record an explicit waiver with the owner's name. |
| **S2** | Minor | A defect with a visible symptom — a wrong log line, a thinner answer, a confusing message. Degrades the product but does not mislead. | Fix, or file with a named owner. |
| **S3** | Nit | Readability, comment quality, a dead import. | Optional. Never block on an S3. |

**The S0 rule that matters most here:** a change that turns a *loud* failure into a *quiet* one is S0, even
if it makes the code shorter. This is the class the project keeps re-discovering.

---

## 3. The five axes

Every review walks these five. Each question is drawn from a defect that actually happened.

### Axis A — Silence

> **Does this change fail loudly?**

- If this raises, who sees it? If it does not raise, what does the user see instead?
- **A `try/except` that swallows** — is the caller told anything? `except Exception: pass` is S1.
- **An early `return` with a default** — is the default distinguishable from a real empty result? The
  project's standing rule: *a failed read is not an empty source.*
- **A filter or gate that drops something** — is the drop logged? (`_is_duplicate_reply`'s fix logged every
  drop for exactly this reason.)
- **A feature switch** — when off, does it produce *no output and no error* by design, and does the reviewer
  know that is intended?
- **A loader that skips** — `discover_actions()` skips an invalid `TOOL` without raising. Any new discovery
  path must be checked for the same shape.

### Axis B — Honesty

> **Does it distinguish a finding from a limitation from a failure?**

The project has three sentences and never merges them:

| Burmese | Meaning |
|---|---|
| `မတွေ့ပါ` | **finding** — I looked, and it is not there |
| `မရှိပါ` | **limitation** — it is not in this window / not in this source |
| `မချိတ်နိုင်ပါ` | **failure** — I could not look at all |

- **Which one is this?** Name it explicitly in the review.
- **The first sentence is the one that gets spoken.** A tool result that opens with "not found" and explains
  underneath will be paraphrased by the model as *"there is no news"*. Measured, in a live session. If a
  source could not be read, **that is the first sentence**.
- **Does the answer claim coverage it did not achieve?** *"I checked both papers"* when one held 1 readable
  row out of 23 is an S1.
- **Is a partial result reported as complete?** 42 readable rows out of a 32-page issue is partial. Never say
  "readable now" without the fraction.
- **Does a claim report success it cannot verify?** `Typed: <text>` was true of the text and silent about
  *where it went* — that was F10.

### Axis C — Trust

> **Is model output treated as untrusted input, and is anything irreversible gated?**

- **Model-written, code-executed.** A plan the model wrote that the code then runs is untrusted input.
  `core/safe_command.py` guards `dev_agent`'s `run_command` and its dependency list. Any new path of this
  shape needs the same guard.
- **`shell=True`** turns an argv into a shell command string. Legitimate only when every part is a literal.
- **Irreversible actions** go through `core/confirm.py`. **Reversible** ones should not — do it and push an
  undo (`core/undo.py`). The gate is drawn at reversibility, not at alarm: `send_message` (cannot be
  unsent) needed it; `delete_file` (Recycle Bin + undo) did not.
- **Confirmation tokens must not come from the model.** A `confirmed` parameter is a convention, not a gate.
- **Secrets** live in `config/api_keys.json` only, read through `memory/config_manager.py`. Never into
  context; verify a write by key **counts**.
- **Path confinement.** `file_controller._SAFE_ROOTS` via `_is_safe_path()`, plus `file_access_roots` from
  `api_keys.json` — hand-edited by the user, so JARVIS cannot widen its own boundary. A configured root is
  allowed but **cannot be deleted**. Never a whole drive.
- **Prompt injection.** JARVIS reads untrusted documents (news articles, web pages, newspaper pages) as a
  matter of routine. Every role prompt carries `with_defence()`. Never inline a role prompt.

### Axis D — The model-facing surface

> **The tool description and the parameter names are part of the product.**

This axis exists because it was the single most expensive lesson in the project.

- **A tool description steers the model harder than the code steers it.** `news_section`'s own description
  said *"do NOT use for 'X အကြောင်း သတင်းရှိလား' with an arbitrary topic"* — the owner asked exactly that
  shape with a **section** name, and the model went elsewhere. **A section name is never "an arbitrary
  topic".**
- **A parameter that answers the question must not then be refused.** `reporter_news(action='day')` with
  `days=2` and no literal date said *"which day?"* — the user had already said "yesterday".
- **Does the description say which source this tool owns, and when NOT to use it?** When two tools could
  answer, the split belongs in both descriptions, not only in the routing code.
- **Is the answer shape the owner's?** (`**သတင်းစာ**` / `**ကဏ္ဍ**` / `**ခေါင်းစဉ်**` / `**အနှစ်ချုပ်**`.)
- **An unknown value must never degrade to "everything".** `kind="rice"` was silently dropped and a rice
  price question was answered with fire-balloon festival dates. Refuse, and name the real options.

### Axis E — Evidence

> **Is the claim measured, and read back?**

- **A live test is only evidence if the answer is read back out of the source row.** A 200 with well-formed
  audio is not evidence. A green check that never looked at the output is not evidence.
- **A live test that passes an optional argument the model may not fill is not the owner's test.** Test the
  question the owner actually asks.
- **A probe that stops early reports a defect that does not exist.** Two of the project's own probe bugs
  did exactly this. Drain until idle; do not break on the first `turn_complete`.
- **A check must assert on a rule, not on a measurement.** Three times in one day a check failed *because
  the data got better*. If a check breaks when the database advances, it is pinned to the wrong thing.
- **When a check fails, do not relax it — re-frame it.** And check whether something real is underneath:
  one "stale" failure was sitting on top of a genuine bug in `reporter_news`'s `people` branch.
- **Count, do not reason.** The Burmese medial rules were decided by counting 6.9 M characters, not by
  reasoning about them. `/g\d+` was proven too narrow by counting 325,695 characters of clean text.
- **A limitation is not a finding** — and a limitation stated as a finding is an S1.

---

## 4. Mandatory rules by artifact

### 4.1 A new or changed tool (`actions/*.py`)

| # | Rule | Severity if wrong |
|---|---|---|
| 1 | `TOOL` has `name`, `description`, `parameters` (`"type": "OBJECT"`), `handler` — or the loader skips the file **silently** | S0 |
| 2 | The handler signature is `fn(parameters: dict = None, ...)`. Never `fn(query="", **_)` — it swallows the whole argument dict | S0 |
| 3 | The handler is checked **through the dispatcher** (`_via` → `_call_handler`), never by calling it with keywords directly | S0 |
| 4 | The description names the source it owns and when not to use it | S1 |
| 5 | An unknown value is refused with the real options named; it never degrades to "everything" | S1 |
| 6 | Failure, limitation and finding are three different sentences | S1 |
| 7 | The handler does not raise into the voice path — it returns a sentence | S1 |
| 8 | Any irreversible side effect is gated by `core/confirm.py`; any reversible one pushes an undo | S0 |
| 9 | Shared sentences live in `actions/_reporter_common.py` / `_newsroom_common.py`, not copied | S2 |

### 4.2 A change to `core/` (routing, dispatch, entities, memory, extraction)

| # | Rule | Severity |
|---|---|---|
| 1 | Routing precedence in `main.py::_news_route` is **load-bearing**; a change states which branch moved and why | S1 |
| 2 | Memory writes carry `source: "user" \| "model"`; nothing is learned on the model's own initiative | S1 |
| 3 | A correction is a **re-hearing**, not a disagreement — `record_correction`'s share threshold (0.65) is respected | S0 |
| 4 | Two spellings of one figure, or two canonicalizers for one rule, are collapsed to one | S2 |
| 5 | Grep the identifier before adding a module-level table — Python keeps the last and the earlier one is dead code | S2 |
| 6 | `str.isdigit()` is not used on Burmese text; `re.search(r"[0-9]")` is | S2 |
| 7 | Burmese literals are edited by anchoring on ASCII lines; codepoint length is **measured**, never guessed | S2 |
| 8 | Zawgyi is never silently rewritten on the read path — `looks_like_zawgyi()` **says** it is unreadable | S1 |

### 4.3 A change to prompts (`core/prompt.txt`, `core/agent_prompts.py`)

| # | Rule | Severity |
|---|---|---|
| 1 | Every role prompt is inside `with_defence()`; none is inlined | S1 |
| 2 | One owner per fact — the same fact is not stated in two prompt sources | S2 |
| 3 | A routing rule written in prose is **not** a rule. If it must hold, it also exists in code (`_news_route`) | S1 |
| 4 | The prompt states which tool owns which source, matching the tool descriptions | S1 |

### 4.4 A change to extraction or classification (`ingest_engine.py`, `news_sections.py`, `jarvis_categories.py`)

| # | Rule | Severity |
|---|---|---|
| 1 | The artefact gate is a **ratio**, not a presence test | S0 |
| 2 | Glyph-name patterns use the general form `/[A-Za-z]+\d+` — not `/g\d+` | S0 |
| 3 | Vision calls are chunked (~6 pages); a model handed a hard task returns something plausible | S1 |
| 4 | Classification runs by **strength of evidence** (headline-or-lede for the offices), not by keyword count | S1 |
| 5 | A rule change uses `action="rebuild"` — `index` only fills never-classified rows and reports false success | S0 |
| 6 | The result is verified by **reading the counts back** out of the column written to | S1 |
| 7 | The fraction is reported — "42 readable" is not "readable" | S2 |

### 4.5 A change to a check suite (`check_*.py`)

| # | Rule | Severity |
|---|---|---|
| 1 | The check asserts a **rule**, not a live measurement (row counts flake while the pipeline loads) | S1 |
| 2 | A failing check is **re-framed**, not relaxed — and checked for a real bug underneath | S1 |
| 3 | A new guard is proved non-vacuous (it fails when the bug is reintroduced) | S1 |
| 4 | The suite stays offline where it can be (`check_entities.py`, `check_topic.py`) | S3 |
| 5 | The live-fetch suites are not run in parallel | S2 |

---

## 5. Anti-pattern catalogue

Named, because a named pattern is one a reviewer can recognise quickly.

| Pattern | Why it is a defect | The real instance |
|---|---|---|
| **The silent skip** | The thing did not happen and nothing said so | `discover_actions()` skips an invalid `TOOL`; only it distinguishes "file exists" from "callable" |
| **The swallowed argument** | The handler sees no input and returns a plausible empty answer | `fn(query="", **_)` — six tools |
| **The keyword count as evidence** | A count is not a call-site reading | F6's first version was wrong in 4 files out of 4 |
| **The keyword filter as a gate** | A substring test decides whether the assistant speaks | `new in prev` blanked the reply; `_is_duplicate_reply` fixed it |
| **The default that means "everything"** | An unrecognised filter silently widens the search | `kind="rice"` → fire-balloon dates |
| **The gate that is a convention** | The model writes the confirmation token | `confirmed=yes` |
| **The dead duplicate table** | Python keeps the last; the fix does nothing | A second `_PRICE_ALIASES` |
| **The gate that cannot see it has already run** | Idempotence must be *stored*, not inferred from the input | The Zawgyi ledger — 188 rows written twice |
| **The success message for nothing done** | Prints success having done nothing | *"inserted 0 of 0"*, exit 0 |
| **The limitation spoken as a finding** | The user is told something false about a source | *"there is no news"* from a correct tool output |
| **The claim of coverage not achieved** | *"I checked both papers"* | One paper held 1 readable row of 23 |
| **The probe that stops early** | Reports a defect that does not exist | Broke on the first `turn_complete`; 610 KB of audio followed |
| **The check pinned to a measurement** | Fails when the data improves | Three times in one day |
| **The description that steers wrong** | The model obeys the description over the code | `news_section` and a section name |
| **The parameter that answers and is refused** | The user already answered the question | `action='day'` with `days=2` |

---

## 6. How to report a finding

Every finding — in a review, in `AGENT-AUDIT.md`, in a change record — carries six fields. This is the
format `AGENT-AUDIT.md` used, and it is why its findings survived a second pass.

1. **Evidence** — the file, line, and the measurement. A quote, a count, a console line.
2. **Mechanism** — *how* it goes wrong, step by step. Not "this is risky".
3. **Root cause** — the design decision that allowed it.
4. **Confidence** — 0.0–1.0, and what would raise it.
5. **Fix** — what changed, or what should change.
6. **Verification** — how we know the fix works, and which check now holds it.

A finding without **evidence** is an opinion. A finding without **verification** is a hope. Both are
welcome as notes — neither is a review finding.

---

## 7. Disposition

| Outcome | Meaning |
|---|---|
| **Approved** | No S0/S1 open. Warnings reviewed and recorded. |
| **Approved with conditions** | S2/S3 open with a named owner and a date. |
| **Changes required** | Any open S0/S1. The change is not merged. |
| **Waived** | An S0/S1 accepted deliberately. Requires the owner's explicit decision and a written reason in the change record. Never silent. |

**A waiver is a decision, not a default.** "It works on my machine" is not a waiver. "This is S1 because a
failed read is spoken as an empty source; accepted because the read is now retried three times and the
retry is logged" is a waiver.

---

## 8. Known limits of this standard

Recorded honestly, because a standard that claims more than it delivers is its own defect.

- **The gate cannot see behaviour.** `review_gate.py` reads syntax trees. It found a real defect
  (`file_controller.py:420`) and it cannot find a wrong answer.
- **The suite cannot see what the model will say.** Every check reads a string; none asks how the model will
  paraphrase it. That is how four defects survived 430/430.
- **There is no version control.** A "change" is a set of files, not a diff. The process compensates
  (`CODE-REVIEW-PROCESS.md` §3) but cannot show you what moved.
- **The reviewer is often the author.** Self-review is the weakest form. Axis D and Axis B are the two where
  a second reader earns the most, because the author already believes the answer.

# Code review process — Mark-LIV / JARVIS

**Companion to:** `CODE-REVIEW.md` (the standards) · **Record:** `CHANGE-REVIEW-TEMPLATE.md` ·
**Automated half:** `review_gate.py` · **Adopted:** 2026-10-01

---

## 1. The constraint that shapes everything

**There is no git repository.** Measured 2026-10-01: `E:\Mark-LIV-main\.git` does not exist. So this process
cannot be a pull-request flow, and it does not pretend to be one.

What that costs, stated plainly:

- There is **no diff**. A reviewer cannot see what moved — only what the files now contain.
- There is **no blame**. A defect cannot be traced to the change that introduced it.
- There is **no rollback**. A bad change is undone by hand.

What replaces it: **the change-set record**. Every review names the files it touched and what changed in
each, so the change exists as a described unit even though the history does not. The template is
`CHANGE-REVIEW-TEMPLATE.md`; a filled example is `docs/STATUS-2026-10-01.md`.

> **Recommendation (not yet done):** initialise git. Even local-only, with no remote, it turns every review
> from a description into a diff and gives the project a rollback. This is the single highest-value
> infrastructure change available and it is outside the scope of this document.

---

## 2. Roles

| Role | Who | Owns |
|---|---|---|
| **Author** | whoever makes the change (often the assistant) | self-review, the change record, running the gate |
| **Reviewer** | a second reader — the assistant reviewing the owner's change, or the owner reviewing the assistant's | the five axes in `CODE-REVIEW.md` §3, the WARN verdicts |
| **Owner** | Mr. Thwin | waivers, anything S0/S1, and every decision that leaves the machine |

**On self-review.** The author is usually also the reviewer. That is the weakest configuration, and it is
recorded as a known limit. It is why the gate is automated: the machine has no stake in the change being
right. When the change touches Axis B (honesty) or Axis D (the model-facing surface), get a second reader —
those are the two where the author already believes the answer.

---

## 3. When a review is required

**Required** for any change to:

- `main.py`, anything in `core/`, anything in `actions/`
- a `check_*.py` suite
- `config/*.sql`, `requirements.txt`, or the shape of `config/api_keys.json`
- `core/prompt.txt` or `core/agent_prompts.py`

**Not required** (record it in the daily log instead):

- a typo or comment fix with no behaviour change
- a new check that only adds coverage and touches no product code
- a documentation file
- a data operation run by a script that already exists and is unchanged

**A change is not "done" until the gate is green and the change record exists.** "It works" is not done.
"It works and here is how we know, and here is what could still be wrong" is done.

---

## 4. The five gates

Run in order. A later gate does not excuse an earlier one.

### Gate 1 — Intent

Write down, in two sentences, **what changes and why**. If the change has no answer to "what would be
different for the owner", it is not a change yet — it is an experiment, and experiments do not need a review
record, only a note.

### Gate 2 — Self-review against the standards

Walk the five axes in `CODE-REVIEW.md` §3. Answer each axis **in writing** in the change record, even when
the answer is "not applicable". The act of writing the answer is the review; a tick in a box is not.

### Gate 3 — The gate script

```bash
py review_gate.py --full        # static checks + check_agent.py + the offline suites
```

- **0 failures is required.** A `FAIL` is not negotiable; fix it or waive it (Gate 4).
- **Every `WARN` needs a verdict.** A warning is a review trigger: read the call site, then write either
  "reviewed — safe, because …" or raise it as a finding. A warning with no verdict is an unfinished review.
- Run `--full` in the **foreground**. The project's rule: a background task is killed when the turn ends, and
  `check_agent.py` takes ~2 minutes.
- **Do not run the live-fetch suites in parallel** — `check_greeting.py` has flaked alongside a background
  `check_agent.py`.

### Gate 4 — Second read

The reviewer walks the five axes independently, and specifically:

- opens **every call site** the gate flagged,
- asks Axis A of every new `except`, `return` and `continue`,
- asks Axis B of every new user-facing string: is this a finding, a limitation, or a failure?
- asks Axis D of every new or changed tool description.

### Gate 5 — Record and close

Fill in the change record, assign every finding a severity and a disposition, and append a one-line note to
`.workbuddy-ai/memory/YYYY-MM-DD.md`. An unrecorded review did not happen.

---

## 5. The gate script

`review_gate.py` is **read-only** — it never writes, deletes, or imports the app.

```bash
py review_gate.py --static   # seconds: syntax, TOOL contract, hazards, memory budget
py review_gate.py            # + the fast offline suites (check_entities, check_topic, check_sections)
py review_gate.py --full     # + check_agent.py (~2 min), check_startup, check_sources
py review_gate.py --json     # machine-readable, for a future CI hook
```

| Check | Answers | Level |
|---|---|---|
| **G1** compile | does every `.py` parse? | FAIL |
| **G2** TOOL shape | would the loader skip a tool file silently? | FAIL |
| **G3** handler signature | does the handler accept `parameters` by name? | FAIL |
| **G4** duplicate tables | is a module-level name defined twice (the second wins, the first is dead)? | WARN |
| **G5** dangerous APIs | `shutil.rmtree` / `os.system` / `eval` / `exec` / `shell=True` — read the call site | WARN |
| **G6** `str.isdigit()` | used on text that may contain ၀-၉ | WARN |
| **G7** literal secrets | a credential in a `.py` instead of `api_keys.json` | FAIL |
| **G8** tool description | too short, or a news tool that does not name its source | WARN |
| **G9** stale `__pycache__` | a fix that will look unapplied | WARN |
| **G10** memory budget | an injected file that will be truncated silently | FAIL |
| **S** suites | the project's own `check_*.py` | FAIL |

**Why FAIL and WARN are split this way.** `FAIL` means unambiguously wrong — no judgement needed. `WARN`
means the pattern is legitimate in some call sites and dangerous in others, so a human reads the call site.
The distinction is the F6 lesson: a gate that fails on a keyword trains the reviewer to ignore it.

Checks G2–G8 read the **syntax tree, not the text**, so a pattern inside a docstring, a comment, a denylist
or a test's own data is not reported. The first version of the gate scanned raw text and produced three false
positives out of three.

**The gate is not the review.** It cannot see behaviour. It found one real defect
(`file_controller.py:420` — `shutil.rmtree` in an undo path, which hangs under this machine's trash shim) and
it will never find a wrong answer.

---

## 6. Evidence rules

These apply to any claim in a change record, a review, or a report.

1. **A live test is evidence only if the answer is read back out of the source row.** A 200 with well-formed
   audio is not evidence. A green check that never looked at the output is not evidence.
2. **A live test that passes an optional argument the model may not fill is not the owner's test.** Test the
   question the owner actually asks, in the words the owner uses.
3. **A probe that stops early reports a defect that does not exist.** Drain until idle.
4. **Count, do not reason** — for any claim about a corpus. The medial rules came from 6.9 M characters.
5. **Report the fraction.** "42 readable" is not "readable".
6. **A failed read is not an empty source.** Never let a read failure reach the user as a finding.
7. **A limitation is not a finding.** Say what could not be read, first.
8. **Never say "should work".** Either it was measured, or it is listed as unverified.

---

## 7. Severity → sign-off

| Severity | Who signs | Evidence needed |
|---|---|---|
| S0 | **Owner** | the fix, plus the check that now holds it |
| S1 | **Owner** (or a recorded waiver) | the measurement that proves the fix |
| S2 | Author + reviewer | a note in the change record |
| S3 | Author | none |

A waiver of an S0/S1 is written into the change record with the owner's name and the reason. **Silent
waivers are the defect this process exists to prevent.**

---

## 8. Rollout

The mechanism is introduced in four stages. **We are at Stage 1.**

| Stage | What it is | Status |
|---|---|---|
| **1 — Written** | `CODE-REVIEW.md`, `CODE-REVIEW-PROCESS.md`, `CHANGE-REVIEW-TEMPLATE.md` exist; `review_gate.py` runs and is clean. | **Done — 2026-10-01** |
| **2 — Applied** | The gate is run on the next real change, and the first change record is filled in. The standards have been used once, so their gaps are known. | **Next.** Blocked on nothing — the next change to `core/` or `actions/` is the trigger. |
| **3 — Habitual** | The gate runs before every change without being asked, and every review produces a record. Warnings get verdicts. | Not started |
| **4 — Enforced** | `review_gate.py` is wired into a workflow (a pre-commit hook, or a wrapper around the run) so a change cannot be called done with the gate red. | Not started — **and blocked on git** (no repo ⇒ no hooks). |

**Stage 1 → 2 needs no new work.** The next change that touches `core/` or `actions/` is the first change
reviewed under this process.

**Stage 4 is blocked** on version control. Without a repository there is nowhere to hang a hook. The interim
substitute is Gate 3 as a step in the change record: the record cannot be closed without a pasted gate run.

---

## 9. Maintenance

- **The gate's rules age.** Each check names the defect it descends from. When a new defect class is found
  and generalised, add a check — and add its motivating measurement to the docstring, as the existing ones do.
- **The standards age faster than the code.** `CODE-REVIEW.md` §4 is per-artifact; when a new artifact type
  appears (a new config format, a new pipeline stage), add a subsection rather than stretching an existing
  rule to cover it.
- **Re-audit.** `jarvis-agent-audit` re-walks the 12-layer agent stack. Run it after any change to the
  system prompt, the memory layers, or tool selection — the layers where a silent failure compounds.
- **The memory budget is a gate, not a suggestion.** `G10` fails when an injected file overruns. On
  2026-10-01 `MEMORY.md` did exactly that and was silently truncated; it was split into an index
  (`MEMORY.md`) plus detail (`RULES.md`). Keep it that way.

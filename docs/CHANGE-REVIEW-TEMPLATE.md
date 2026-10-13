# Change review — <short title>

<!-- Copy this file to `docs/changes/YYYY-MM-DD-<slug>.md` and fill it in. Delete the guidance comments.
     A change is not "done" until this record exists and the gate is green.
     The standards this form implements: docs/CODE-REVIEW.md
     The process: docs/CODE-REVIEW-PROCESS.md -->

| | |
|---|---|
| **Date** | YYYY-MM-DD |
| **Author** | |
| **Reviewer** | |
| **Owner sign-off** | required if any S0/S1 (see §7 of the process) |
| **Severity of the change** | S0 / S1 / S2 / S3 — the highest severity of anything it touches |

---

## 1. Intent

**What changes** (two sentences):

**What is different for the owner** (if the answer is "nothing", say why the change is worth making):

**What this deliberately does NOT do:**

---

## 2. Files touched

There is no git, so this table *is* the diff. Name every file and what changed in it.

| File | What changed |
|---|---|
| `core/…` | |
| `actions/…` | |

**New files:**
**Deleted files:**

---

## 3. The five axes

Answer every axis in writing. "Not applicable" is a valid answer; a blank is not.

### A — Silence: *does this change fail loudly?*
<!-- Every new `except`, `return`, `continue`, feature switch, and filter/gate that drops something.
     If it raises, who sees it? If it does not, what does the user see instead? -->


### B — Honesty: *finding, limitation, or failure?*
<!-- Every new user-facing string. `မတွေ့ပါ` (finding) / `မရှိပါ` (limitation) / `မချိတ်နိုင်ပါ` (failure).
     The FIRST sentence is the one the model speaks — is it the true one? -->


### C — Trust: *is model output untrusted, and is anything irreversible gated?*
<!-- Model-written code that gets executed · shell=True · confirm.request() vs core/undo.py ·
     secrets · path confinement · prompt injection -->


### D — The model-facing surface: *do the descriptions and parameters steer correctly?*
<!-- Tool descriptions · parameter semantics · the answer shape · does an unknown value refuse
     rather than degrade to "everything"? -->


### E — Evidence: *is the claim measured, and read back?*
<!-- The measurement, the count, the read-back. What was NOT verified? -->


---

## 4. Gate

```
$ py review_gate.py --full
```

**Result:** <paste the summary line>

**Every WARN needs a verdict** — a warning is a review trigger, not a verdict:

| Check | Where | Verdict (reviewed — safe because … / raised as finding #N) |
|---|---|---|
| G5 | `actions/…:NNN` | |
| G6 | `actions/…:NNN` | |

---

## 5. Findings

One block per finding. The six fields are mandatory (see `CODE-REVIEW.md` §6). A finding without evidence is
an opinion; without verification, a hope.

### Finding 1 — <title>

- **Severity:** S0 / S1 / S2 / S3
- **Evidence:** <file:line, the quote, the count, the console line>
- **Mechanism:** <how it goes wrong, step by step>
- **Root cause:** <the design decision that allowed it>
- **Confidence:** 0.0–1.0, and what would raise it
- **Fix:**
- **Verification:** <how we know it works, and which check now holds it>

---

## 6. Disposition

| Outcome | *(tick one)* |
|---|---|
| Approved | |
| Approved with conditions | |
| Changes required | |
| Waived (S0/S1 only — owner's name and reason required) | |

**Conditions / waiver reason:**

**Follow-ups filed** (with a named owner):

---

## 7. Memory note

- [ ] A one-line note appended to `.workbuddy-ai/memory/YYYY-MM-DD.md`
- [ ] Any lasting rule added to `.workbuddy-ai/memory/RULES.md` (and indexed from `MEMORY.md`)
- [ ] `py review_gate.py --static` still shows `G10` green (the memory files are within budget)

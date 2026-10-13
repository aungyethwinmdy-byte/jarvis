# JARVIS PC Cleaner — design review and additions

Review of the proposed four-part cleaner, checked against **this** codebase
(`E:\Mark-LIV-main`) and measured on **this** machine. The plan is sound; most of
what follows is either a conflict with something the project already has, or a
place where the real win on this machine is somewhere the plan does not look.

---

## 0. What is actually on this machine (measured 2026-09-29)

Before designing a cleaner it is worth knowing what it would clean.

| Target | Size | Needs admin |
|---|---|---|
| `%TEMP%` | **1.29 GB** | no |
| `hiberfil.sys` | **1.56 GB** | yes |
| `C:\Windows\SoftwareDistribution\Download` | 0.18 GB | yes |
| `C:\Windows\Temp` | 0.12 GB | yes (readable, not writable) |
| `C:\Windows\Logs\CBS` | 0.02 GB | yes |
| WER crash dumps | ~0 | yes |
| `C:\Windows.old` | absent | yes |
| `C:\ProgramData\Package Cache` | 0.01 GB | yes |

| Drive | Total | Used | Free |
|---|---|---|---|
| **C:** | 128.4 GB | 91.2 GB | **37.2 GB** |
| E: | 110.0 GB | 31.3 GB | 78.7 GB |

Other measured consumers on C: — `Program Files (x86)` 8.46 GB, `Program Files`
6.72 GB, `AppData\Local` 2.73 GB+, `Documents` 1.48 GB, `WinSxS` 1.09 GB+,
`AppData\Roaming` 0.86 GB+.

**The honest headline: part 1 of the plan yields about 1.6 GB on this machine.**
`hiberfil.sys` alone is 1.56 GB and the plan does not mention it. That is not an
argument against the plan — 1.6 GB out of 37 GB free is worth having — but it
should be built knowing the ceiling, or the first run will feel like a
disappointment.

---

## 1. Four things in the plan that conflict with this codebase

### 1.1 The confirmation guardrail already exists — do not build a second one

`core/confirm.py` is a working, tested gate with a clear rule, stated in its own
docstring: **reversible work is done at once and pushed onto `core/undo.py`;
only irreversible work is parked behind `confirm.request()`.**

So "Voice Confirmation Guardrail" is not a feature to write — it is a call to
make. The shape is:

```python
return confirm.request(
    key="pc_cleaner.empty_recycle_bin",
    title="Empty the Recycle Bin?",
    detail="This cannot be undone, and it also removes the undo history.",
    run=lambda: _empty_recycle_bin(),
)
```

The rule to apply when deciding what gets gated: **deleting a temp file is
irreversible; moving something to the Recycle Bin is not.** That is the line
`confirm.py` draws, and the cleaner should follow it rather than inventing a
second notion of "important".

### 1.2 The subprocess architecture is wrong for this project

The plan suggests a separate `cleaner.py` worker driven by
`--mode=quick` / `--mode=deep --scan-only`, with JARVIS spawning it as a
subprocess. That is a reasonable pattern in general and it is the wrong one
here, for four reasons:

1. **Actions are auto-discovered, one `TOOL` dict per file.** Two dicts in one
   file registers *neither*, silently. The voice path is
   `actions/pc_cleaner.py` with exactly one `TOOL`, and the handler dispatches
   the modes.
2. **A subprocess cannot reach the undo stack.** `push_undo()` lives in the
   parent process. Deleting in a child means the undo entries have nowhere to
   go, and `file_controller`'s whole delete story (trash + undo + protected
   folders) is bypassed.
3. **`core/safe_command.py` would flag it.** That module exists because the
   model once wrote its own `run_command` into a plan and the code executed it.
   Spawning our own script by name is fine, but it re-opens the door the project
   deliberately closed, for no benefit.
4. **The crash isolation it buys is already there.** `_execute_tool` wraps every
   action in `try/except` and speaks the error. A raised exception in an action
   does not take JARVIS down.

Keep a CLI entry point for testing and for the scheduled task. The voice path
should be an action.

### 1.3 Half of part 1 and all of the DISM step need administrator rights

`C:\Windows\Temp`, `Prefetch`, `SoftwareDistribution`, `CBS` logs, `cleanmgr.exe`
and `dism.exe` all require elevation. The app does not run elevated, and the
plan does not mention this.

What that means in practice:

- `%TEMP%` (1.29 GB of the 1.6 GB) — **no admin needed.** This is the part that
  works today.
- `C:\Windows\Temp` is *readable* unelevated (120 files measured) but deletion
  fails. A scan that lists it and then fails to clean it is worse than not
  listing it.
- **Elevation has to be a visible, user-driven step**, the way
  `dashboard/server.py` already does it — write a `.bat`, run it, fall back to
  `ShellExecuteW` with the `runas` verb so Windows shows the UAC prompt. Reuse
  that pattern; do not invent a second one.

**Design consequence:** split the report by what is achievable now versus what
would need a UAC prompt, and say so in the spoken summary. *"1.29 GB can be
cleared now; another 0.3 GB needs administrator rights."*

### 1.4 "Empty Recycle Bin" fights the project's own undo design

`file_controller.delete_file` deletes via `send2trash` **and** pushes an undo
that restores from the bin. Emptying the bin therefore:

- makes every previous `undo` in the session impossible, and
- silently invalidates the promise `USER-GUIDE.md` makes — *"ဖိုင်ဖျက်တာ
  Recycle Bin ထဲ ထည့်တယ် (တကယ် မဖျက်ဘူး)၊ undo ပြန်လုပ်လို့ရတယ်"*.

If it ships at all it needs the hardest gate in the system, a spoken warning
that names the undo consequence, and a line in the manifest. **Consider not
shipping it.** Windows already empties the bin on a schedule.

---

## 2. What the plan is missing — safety

These matter more than any feature, because the failure they prevent is
unrecoverable.

**2.1 A hard allowlist of paths, enumerated in code.** Never "everything under
X". The cleaner touches `C:\Windows\...` which is outside `Path.home()` and
therefore outside `file_access_roots` — so it cannot go through
`file_controller`'s guard, and it must not quietly bypass it either. It needs
its own list, written out, one line per target.

**2.2 An explicit never-delete list.** For this user specifically — a
journalist — a cleaner that eats a draft is far worse than a full disk:

- **by extension, anywhere, including inside temp:** `.docx .doc .pdf .md .txt
  .xlsx .xls .pptx .odt .rtf .csv`
- **by location:** `Desktop`, `Documents`, `Pictures`, `Videos`, and the whole of
  `E:\2026 npt news` (the news archive), `E:\AI_NEWSROOM`

**2.3 An age threshold, not just a lock check.** A file in `%TEMP%` that is not
locked may still belong to something running right now — an installer mid-run,
an app's session cache. **Not locked ≠ not needed.** Skip anything modified in
the last N hours (24 is a sane default, and it should be configurable).

**2.4 Dry-run as the default, not a flag.** Deletion should always be the second
step, after a scan the user has seen. `--scan-only` as an option means the
dangerous path is the default path.

**2.5 A deletion manifest.** A line per deletion — path, size, when, which mode
— in a file the user can read. It is the only way to answer *"what did you
delete?"*, and the only way to debug *"app X stopped working"*. The project
already writes an audit trail for the newsroom; this deserves the same.

**2.6 Trash, not delete, outside `%TEMP%`.** Inside `%TEMP%` permanent deletion
is the point. Everywhere else — Downloads triage, large-file cleanup, dev junk
— use `send2trash` + `push_undo`, the established pattern.

**2.7 Idempotent and re-runnable.** A scan interrupted halfway (or stopped by
"stop") must be safe to run again, with no half-state.

---

## 3. What the plan is missing — real space

The plan's part 1 is the classic list. On this machine the classic list is
1.6 GB. These are the places the plan does not look:

**3.1 `hiberfil.sys` — 1.56 GB here, bigger than `%TEMP%`.** `powercfg /h off`.
Disables hibernate *and* Fast Startup, so it is report-and-confirm, never
automatic. Needs admin.

**3.2 System restore points / shadow copies.** Frequently GB-scale and never
mentioned. `vssadmin list shadowstorage` to measure. **Report only** — deleting
restore points removes the user's ability to roll back a bad update.

**3.3 Developer junk — the biggest untapped win on this machine.** The user has
several projects (`E:\ECC-main`, `E:\AI_NEWSROOM`, `E:\Mark-LIV-main`, `E:\Burma
voice assistant`, …) and those trees carry `node_modules`, `.venv`,
`__pycache__`, `dist`, `build`, `.next`. These are GB-scale and 100% regenerable.
The safe rule: **only offer a `node_modules`/`.venv` for deletion when the
project has the lockfile that can rebuild it** (`package-lock.json`,
`requirements.txt`/`pyproject.toml`), and say the rebuild command in the report.

**3.4 App caches.** `AppData\Local` measured 2.73 GB. Electron apps (Teams,
Slack, Discord, VS Code) keep a `Cache`/`Code Cache`/`GPUCache` under
`AppData\Roaming\<app>` or `AppData\Local\<app>`; Spotify and OneDrive keep
large caches too. These are usually safe and usually ignored.

**3.5 Delivery Optimization cache** (`SoftwareDistribution\DeliveryOptimization`)
— often GB-scale, absent here today. Cheap to detect.

**3.6 Thumbnail and icon cache** — small, safe, easy.

**3.7 Duplicate files — report only.** Hash-based, and never auto-delete. Two
files with the same hash are not necessarily the same document to the person who
wrote them.

**3.8 `C:\ProgramData\Package Cache` — report, never delete.** It looks like
junk and it is what uninstall and repair use.

---

## 4. What the plan is missing — voice UX

These are the parts that are specific to *this* project, and the ones that would
be discovered only after shipping.

**4.1 Numbers must render in Burmese.** The project has `core/timefmt.py` for
exactly this problem. `"1.8 GB freed"` spoken with ASCII digits is read badly.
The summary must go through the same Burmese-number path the date and time use.

**4.2 The scan must not block the voice loop.** A deep scan runs for minutes. Run
it with `asyncio.to_thread`, keep JARVIS answering, and make *"ရပ်လိုက်"* work
mid-scan. The project already uses this pattern for the vision capture and the
newspaper download.

**4.3 Cap what is returned to the model.** A list of 5,000 file paths would blow
the context window and cost money for nothing. Return a **summary plus the top
N** — the model does not need the 4,900th temp file.

**4.4 Say progress, and stay interruptible.** "Scanning… about halfway" is the
difference between a feature and a hang.

**4.5 Never clean while the user is mid-task.** Clearing a browser cache during
a download, or killing a process during a build, is how a cleaner earns a
reputation for breaking things. `actions/system_monitor.py` already samples the
machine every 10 seconds — reuse it as the gate rather than adding new probes.

**4.6 Scheduling.** `actions/reminder.py` already drives Windows Task Scheduler
via `schtasks`. "Clean every Sunday at 3am" is that pattern, not a new one.

---

## 5. Two things I would advise against

**5.1 RAM "boosting" with `SetProcessWorkingSetSize` is mostly placebo.**
Trimming a working set moves pages into the page file; Windows faults them back
in on next use. Task Manager looks better and the machine is often **slower**,
because the memory was not wasted — it was cache. Windows' own memory manager
already trims working sets under pressure.

What is worth building instead: **report actual memory pressure and name the top
consumers.** If an app is genuinely leaking, the fix is restarting that app, and
the cleaner's job is to identify it — not to perform a trick that produces a
number rather than a result.

**5.2 "Not Responding" is usually transient.** A busy app and a hung app look
identical in the task list. The plan already says *prompt* rather than kill —
keep it that way, and never offer to kill an editor, an Office document or a
browser with unsaved work without naming what is at risk.

---

## 6. Suggested shape

```
actions/pc_cleaner.py          one TOOL dict, handler dispatches on `mode`
    scan      read-only, always safe, the DEFAULT
    quick     %TEMP% (age > 24h, unlocked) + browser cache + thumbnails
    deep      + SoftwareDistribution, CBS, WER, app caches, dev junk
    report    the deletion manifest
```

Return a structured summary, not a file list:

```
mode, freed_bytes, would_free_bytes, skipped_locked, skipped_recent,
needs_admin_bytes, top_items[5], manifest_path
```

and let the model speak it in Burmese with Burmese numerals.

**Build order that keeps every step shippable:**

1. `scan` + the manifest + the never-delete list — pure reading, no risk, and it
   is what makes the rest trustworthy.
2. `quick` on `%TEMP%` only, with the age threshold, trash outside temp, undo.
3. Browser cache, with the browser-closed check.
4. Everything needing admin, behind the existing `runas` elevation pattern.
5. The rest, in descending order of measured size.

---

## 7. The one-line summary

The plan is a good cleaner. Two things would make it a good *JARVIS* cleaner:
**reuse `confirm.py` and `undo.py` instead of building parallel safety**, and
**measure before choosing targets** — on this machine the classic list is 1.6 GB,
while hibernate is 1.56 GB and the project trees on E: are likely larger than
both.

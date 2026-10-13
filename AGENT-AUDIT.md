# Agent architecture audit — Mark-LIV / JARVIS

Run 2026-09-28, using the **12-layer agent stack** framework from the ECC skill
`agent-architecture-audit` (`E:\ECC-main\skills\agent-architecture-audit`). That framework's premise is that
an agent system hides its failures behind wrapper layers — stale memory, retry loops, text filters, silent
fallbacks — and that the way to find them is to walk the layers and ask what each one can corrupt.

The 12 layers, mapped to this project:

| # | Layer | Where it lives here |
|---|---|---|
| 1 | System prompt | `core/prompt.txt` + `identity_ctx` in `main.py::_build_config` |
| 2 | Session history | the Live session, `session_resumption` |
| 3 | Long-term memory | `memory/long_term.json` via `memory/memory_manager.py` |
| 4 | Distillation | `_save_session_summary`, `pop_last_session` |
| 5 | Active recall | `recall_memory` / `search_memory` |
| 6 | Tool selection | `TOOL_DECLARATIONS` + `actions/` (33 tools) |
| 7 | Tool execution | `main.py::_execute_tool`, `core/action_loader.py` |
| 8 | Tool interpretation | how tool results are returned to the model |
| 9 | Answer shaping | `_clean_transcript`, `_is_repeat_chunk`, `_REPEAT_MIN` |
| 10 | Platform rendering | `ui.py` log, the audio path |
| 11 | Hidden repair loops | `core/gemini.py`'s model ladder, newsroom retries, `_read_pages` |
| 12 | Persistence | `newsroom_watch_state.json`, render caches |

---

## Findings, most severe first

### F1 — critical — every remembered fact was written by the assistant, with no record of where it came from
**Layer 3 (long-term memory) and 12 (persistence).** *Fixed 2026-09-28.*

- **Evidence.** `main.py:933` is the only live writer: the `save_memory` tool hands
  `category`/`key`/`value` straight to `update_memory()`, which writes them to disk. `memory/long_term.json`
  held **5 entries, 0 of them carrying any provenance**. `format_memory_for_prompt()` then re-injects all of
  them into the system prompt on every launch.
- **Mechanism.** The assistant decides what becomes a permanent fact about the user, and the fact is then
  fed back to it as established knowledge. Nothing distinguishes "the user told me this" from "I worked
  this out". So an inference can be repeated back later as something the user said — and the user has no
  way to see which of their own facts the assistant invented.
- **Root cause.** No admission control and no provenance on the memory record.
- **Confidence.** 0.95 — this is not inferred, it is what the code does.
- **Fix, applied.** Every entry now carries `source: "user" | "model"`; the `save_memory` tool declares it;
  the prompt renders model-sourced facts with `[assistant-recorded]` and a one-line legend telling the
  model not to present them as the user's words. Re-stating a fact as the user promotes the label.
  Entries written before this change are left **unmarked** rather than backfilled, because labelling a fact
  the user actually stated as "assistant-recorded" would be a worse lie than saying nothing.

### F2 — high — a text filter decides whether the assistant speaks, and it fails silently
**Layer 9 (answer shaping) → 10 (rendering).** *Fixed 2026-09-28.*

- **Evidence.** `main.py:1312`
  ```python
  if full_out and len(full_out) >= _REPEAT_MIN and self._last_out_logged:
      if full_out in self._last_out_logged:
          full_out = ""
  ```
  and `main.py:235` `_is_repeat_chunk()`.
- **Mechanism.** A **substring test** against the previously logged reply blanks the whole reply. Since
  `self._speak_cloned(...)` sits inside `if full_out:`, a false positive means the assistant says nothing at
  all — and nothing is logged to say a reply was dropped. A short reply that happens to appear inside an
  earlier long one is discarded.
- **Root cause.** A log-deduplication heuristic deciding whether audio is produced.
- **Confidence.** 0.7. The false-positive risk is plain from the substring test; the rate has not been
  measured, so this is a structural finding rather than a reproduced incident.
- **Fix, applied.** `_is_duplicate_reply()` replaces `new in prev`: a repeat is now the same text, or most
  of the previous reply, not merely a fragment of it. Every drop is logged, so the next occurrence is
  diagnosable instead of invisible.
  **A character-overlap ratio was tried first and rejected** — Burmese reuses letters so heavily that two
  genuinely different sentences ("ဒီနေ့ သတင်းတွေ ပြောပြပါမယ်" against "မနေ့က သတင်းတွေ ပြောပြခဲ့ပါတယ်")
  scored above 90%, which would have thrown away new answers to fix a rarer problem. The first version of
  this fix was wrong and the test caught it.

### F3 — high — "do not use this for news" is a sentence in a tool description, not a rule in code
**Layer 6 (tool selection).** *Fixed 2026-09-28.*

- **Evidence.** `actions/web_search.py`'s `TOOL` description says *"DO NOT USE THIS FOR A NEWS QUESTION
  ABOUT WHAT IS HAPPENING"* and asks the model to route to `newsroom_search`. Nothing in code checks which
  tool was chosen.
- **Mechanism.** The model can ignore the instruction and still answer, and the answer looks normal.
- **Root cause.** A routing rule enforced only in prompt text.
- **Confidence.** 0.9 — the project's own record contains the incident: a question about Myanmar's president
  returned a Colombian earthquake.
- **Fix, applied.** `main._news_route()` runs in `_execute_tool` **before dispatch**, so it does not depend
  on the model choosing well. It fires only on `web_search`, only when the query carries a news word **and**
  a question marker, and never on a world-news request — that is what `web_search` is for. Two false
  positives were found by testing and closed before shipping: `ဒီနေ့ဘာထူးလဲ` ("what's new today") carries
  no `သတင်း` at all and was being missed, and `သတင်းစာတွေ ဘယ်မှာဝယ်လဲ` ("where do I buy a newspaper")
  contains `သတင်း` inside `သတင်းစာ` and was being sent to the newsroom. Both are checked in
  `check_agent.py`. Every redirect is logged and written to the HUD.

### F4 — medium — the same two facts are stated twice in every system prompt
**Layer 1 (system prompt).** *Fixed 2026-09-28.*

- **Evidence.** `main.py`'s `identity_ctx` says *"သင်၏အမည်မှာ {self._asst_name} ဖြစ်သည်"*, and
  `core/prompt.txt` is rendered with `{assistant_name}` in the same prompt. The user's name arrives both
  from `get_user_name()` and from `format_memory_for_prompt()`'s `Name:` line.
- **Mechanism.** Duplication costs prompt budget on every turn and gives two places for the value to
  disagree.
- **Root cause.** Two prompt sources assembled without a single owner.
- **Confidence.** 0.85.
- **Fix, applied.** One owner per fact. The assistant's name is stated in `identity_ctx` only —
  `core/prompt.txt` no longer carries `{assistant_name}` and says why. The user's name is owned by the
  setting: `format_memory_for_prompt()` takes `known_name` and drops the memory `Name:` line when the two
  agree. **When they disagree the line is kept** — a conflict the model can see is better than one it
  cannot, and silencing it would be the same fault in the other direction.

### F5 — medium — the model ladder can answer with a different model and not say so
**Layer 11 (hidden repair loops).** *Fixed 2026-09-28.*

- **Evidence.** `core/gemini.py::call()` walks LIVE → `gemini-3.5-flash-lite` → `gemini-3.8-flash` and
  returns the first answer; the caller cannot tell which rung produced it. A rung that answers *badly*
  ends the chain exactly like one that answers well.
- **Mechanism.** A degraded answer is indistinguishable from a good one at the call site.
- **Root cause.** Silent substitution inside the ladder.
- **Confidence.** 0.9 — measured: the newspaper reader refused on roughly 1 run in 3 because the weakest
  rung declined and the strong rung behind it never ran. That specific case was fixed in
  `actions/newspaper.py`.
- **Fix, applied.** `gemini.answered_by()` records which rung produced the most recent answer on the
  calling thread, and `_note_answer()` prints a line whenever the answer came from a rung other than the
  first one tried — so a substitution is never silent again, at all eight call sites, not just the
  newspaper's. Thread-local rather than global: calls run concurrently from the Live loop, the UI thread
  and plugin executor threads.

### F6 — high — a message can leave the machine without the user agreeing to it
**Layer 7 (tool execution).** *Fixed 2026-09-28. **This finding was wrong the first time and was rewritten
after checking — see below.***

- **The wrong version.** A first pass counted destructive keywords per action file (`delete`, `remove`,
  `unlink`, …) and concluded that the confirmation gate was wired into one caller out of five:
  `file_controller.py` (28 matches), `file_processor.py` (26), `computer_control.py` (3), `desktop.py` (3)
  were reported as ungated. **Every one of those was a false positive.**
- **What the code actually does.** Reading the call sites instead of counting words:
  - `file_controller.delete_file` → `send2trash` (the Recycle Bin, not a delete), **and** pushes an undo
    (`push_undo(...)` → `_restore_from_trash`), **and** refuses to touch Desktop / Downloads / Documents /
    Pictures / Music / Videos / home.
  - `file_processor.py` and `desktop.py` → their only matches are `tmp_audio.unlink()` on a temp file, and
    `desktop.py` documents outright *"NO move, NO rmtree, NO file deletion"*.
  - `computer_control.py` → the grep returns **nothing at all**; the count of 3 came from a looser pattern
    matching prose.
  This is exactly the design `core/confirm.py` asks for — *"Anything that can be reversed should be done at
  once and pushed onto core/undo.py instead; undo is faster than a question"* — and it was already correct.
- **The real finding.** `actions/send_message.py` sends WhatsApp / Telegram / Signal / Discord / Instagram /
  Messenger messages with **no gate of any kind**, and a sent message cannot be unsent. It also contradicts
  the user's own stated rule: *"Ask before anything that leaves the machine (email, messages, posts)."*
- **Mechanism.** The model calls the tool, the tool drives the desktop, the message is gone. Nothing checks
  that the user agreed to that text, to that recipient, on that platform.
- **Root cause.** The gate was designed for the things that *sound* dangerous (shutdown, WiFi) and this one
  does not sound dangerous at all — the same blind spot the module's own docstring describes for WiFi.
- **Confidence.** 0.95 for the finding; the fix is verified by a test that confirms the gate fires.
- **Fix, applied.** `send_message()` now parks the send behind `confirm.request(...)` and returns the
  sentence for the model to speak. The send itself moved to `_perform_send()`, which runs on the gate's
  worker thread only after CONFIRM. The gate is non-blocking, so this costs no latency.

> **Lesson worth keeping.** Counting keywords is not evidence. The first version of this finding was
> produced by `grep -c` and it was wrong in four files out of four; the second was produced by reading the
> call sites. `AGENT-AUDIT.md` is only worth anything if its findings survive that second pass.

### F7 — low — a fact can be written to memory that nothing ever reads
**Layer 3 (long-term memory) and 12 (persistence).** *Fixed 2026-09-28.*

- **Evidence.** `format_memory_for_prompt()` renders only the categories listed in `_CATEGORY_LABELS`,
  but `remember()` accepted a *different*, hand-written set — and `update_memory()` accepts any category at
  all. `memory/long_term.json` contains `interest/latest_news_topic`, written 2026-09-26; searching the
  whole tree for `interest` outside the JSON file returns **nothing**. The fact is on disk and has never
  been in front of the model.
- **Mechanism.** A write path and a read path that agree by coincidence rather than by construction. Any
  future category added to one and not the other becomes a silent no-op.
- **Root cause.** Two lists that describe the same thing.
- **Confidence.** 0.9. **Checked before reporting:** `sessions` is *not* an orphan — it is a list rather
  than a category table, and `pop_last_session()` reads it for the greeting. The first version of this
  finding would have named it wrongly.
- **Fix, applied.** `remember()` now derives its valid set from `_CATEGORY_LABELS`, so a category that
  renders is exactly the set that is writable. `interest/latest_news_topic` was left on disk rather than
  deleted — it is the user's data, and the honest fix is to stop creating more of them, not to quietly
  remove one.

### F8 — high — the assistant ran a shell command it wrote itself
**Layer 7 (tool execution) → 12 (persistence, via the filesystem).** *Fixed 2026-09-28.*

- **Evidence.** `actions/dev_agent.py` asks a model to plan a project, and the plan carries
  `"run_command": "python main.py"`. `_build_project` then passes that string straight to
  `_run_project()` → `subprocess.run(parts)`. Nothing looked at it. The dependency list comes from the
  same plan and is handed to `pip install` the same way.
- **Mechanism.** The model supplies a command; the code executes it. `subprocess.run(parts)` without
  `shell=True` blocks shell *metacharacters* — `;`, `|`, `&&` arrive as literal arguments — so the blast
  radius is one process rather than a shell script. It does not block **which** process. `["rm", "-rf",
  "/"]` is a perfectly valid argv, and so is `["--index-url=http://…"]` as a `pip` argument.
- **Root cause.** The plan is model output that is treated as configuration rather than as untrusted input.
- **Confidence.** 0.9. This is not a report of an incident — it is what the code does, and it is the shape
  of the failure rather than a prediction that it will happen.
- **Fix, applied.** `core/safe_command.py` — a launcher allowlist (runtimes a project actually starts
  with, including `streamlit`/`uvicorn`/`npm`, so a legitimate plan is not refused), a refuse-anywhere list
  of destructive and privilege-escalating binaries, a refusal of shell syntax, and `safe_package()` for
  dependency names, which rejects anything starting with `-`. The check runs **once, before a file is
  written** — a command that is refused is refused every time, and five identical refusals is not a
  diagnosis. Verified against ten legitimate commands (all allowed) and eleven hostile ones (all refused,
  with a reason the model can act on).

### F9 — high — the assistant claimed to type Burmese and typed nothing
**Layer 7 (tool execution) → 10 (rendering).** *Fixed 2026-09-28.*

- **Evidence.** `actions/computer_control.py`'s `_type()` and the short-text branch of `_smart_type()`
  call `pyautogui.typewrite()`. On Windows, `_pyautogui_win._keyDown` opens with:
  ```python
  if key not in keyboardMapping or keyboardMapping[key] is None:
      return
  ```
  **No exception, no keystroke.** Measured against `KEYBOARD_KEYS`: `'Hello, world! 123'` is fully
  typeable; `'မင်္ဂလာပါ'` has **9 untypeable characters out of 9**.
- **Mechanism.** The text is dropped in silence and the caller is told `f"Typed: {text[:60]}"` anyway.
  `computer_settings`'s dispatcher did the same, returning `f"Typed: {text[:80]}"` without looking at what
  `type_text()` did.
- **The worst shape of it.** A *mixed* string — `'Hello ဆရာ'` — loses only the Burmese and keeps the
  Latin, so the result looks like it worked. For a Burmese-speaking user, that is most strings.
- **Root cause.** A keyboard-mapping API used for text that is not made of keypresses.
- **Confidence.** 0.95 — the silent return is in pyautogui's source and the character counts are measured.
- **Fix, applied.** `_can_typewrite()` asks whether every character has a key, and anything that does not
  goes through the clipboard instead — which `_smart_type` already used for text over 20 characters, so
  the machinery was there and only the short path was wrong. `type_text()` now returns what actually
  happened, and says so plainly when the clipboard is unavailable rather than reporting a success it did
  not get. `computer_settings` returns that result instead of its own claim.

### F10 — high — typing reported success without saying where the text went
**Layer 8 (tool interpretation) → 10 (rendering).** *Fixed 2026-09-28, from a user report.*

- **Evidence.** The user asked JARVIS to type `မင်္ဂလာပါ` in Notepad. The console showed:
  ```
  [JARVIS] 🔧 computer_settings  {'action': 'type_text', 'value': 'Notepad မှာ …'}
  [Settings] ✅ Result: Typed: Notepad မှာ …
  ```
  **Notepad was never opened** — no `open_app` call appears — and the model passed the *whole phrase*,
  including the words "Notepad မှာ", as the text to type. The tool reported success, and the answer the
  user heard was that it had been typed.
- **Mechanism.** `type_text()` types into whatever has focus and cannot open or focus anything, so the
  target is entirely outside its control. Its result said `Typed: <text>` — which is a claim about the
  *text*, not about *where it went*, and the one fact the user needed was missing.
- **Root cause.** Two, and both matter: a tool that reports an outcome it cannot verify, and a `value`
  parameter described as "text to type" with nothing saying it must be the payload alone.
- **Confidence.** 0.95 — this is a reproduced incident with the console output.
- **Fix, applied.** `_active_window_title()` (pygetwindow, already installed) reads the focused window
  before typing, and the result is now `Typed into <window>: <text>` — so a mis-targeted type is visible
  instead of confident. When the window is a console, PowerShell, or JARVIS itself, the result carries a
  warning the model can pass on. The `value` description now states both rules: call `open_app` first
  because this tool cannot focus anything, and put the payload in `value` and nothing else. The typing
  itself is unchanged — it cannot be made to open a window, so the fix is to stop it *lying* about it.

---

## Adopting ECC's three suggested steps — what each became

A proposal arrived suggesting three steps from ECC. What was actually built, and what changed on contact
with the code:

| Proposed | What happened |
|---|---|
| **1.** Copy `planner.md`, `security-reviewer.md`, `deep-research.md` into sub-agent prompt templates | `core/agent_prompts.py` now holds every sub-agent role in one place, carrying ECC's **Prompt Defense Baseline** — which matters more here than it does in ECC, because JARVIS reads untrusted documents (news articles, web pages, newspaper pages) as a matter of routine. `planner.md` and `security-reviewer.md` were adapted; **`deep-research.md` does not exist** (there is a `deep-research` *skill*), so the researcher role was written for this project instead of copied. |
| **2.** Install `before-shell-execution` as a safety guard | The hook is Node.js for Cursor/Claude Code and cannot run here. The *idea* was right and landed on a real fault nobody had noticed: **F8** — `dev_agent` executed a run command the model wrote into its own plan. `core/safe_command.py` guards it. |
| **3.** Add a verification loop to the task flow | `dev_agent` already retried a failing build five times; the missing piece was *reading the result*. Both code paths now end the same way: run until it works, then review before handing it over (`dev_agent._review_files`, `code_helper._verify_code`). |

## What this audit did not find

Worth recording, because a clean result is evidence too:

- **Memory growth is already bounded.** `MEMORY_MAX_CHARS` (200,000) with `_trim_to_limit()` dropping the
  oldest entries *and telling the user it did* (`set_trim_notifier`). The ECC framework warns about
  unbounded memory; this project had already solved it.
- **Tool registration is checked.** `discover_actions()` distinguishes "file exists" from "callable", which
  is precisely the "tools declared but not enforced" trap — here it is enforced at load time.
- **The voice path does not raise.** `core/custom_voice.py` and `core/newsroom_client.py` both convert
  failures into a thinner answer rather than an exception.

---

## Ordered fix plan

| Order | Goal | Why now |
|---|---|---|
| 1 | Provenance on memory | **Done.** An unlabelled inference re-entering the prompt as a user fact is the one failure that compounds silently. |
| 2 | Gate `send_message` | **Done (F6).** A message that has left the machine cannot be recalled, and it was the one irreversible action with no gate. |
| 3 | Validate the model's own run command | **Done (F8).** `dev_agent` executed a command the model wrote into its plan. `core/safe_command.py` now checks it before a single file is written. |
| 4 | Stop the reply filter from silently muting | **Done (F2).** A repeat now has to be most of the previous reply, and every drop is logged. |
| 5 | Code-gate the news route | **Done (F3).** `_news_route()` runs before dispatch, so it no longer depends on the model choosing well. |
| 6 | One owner per prompt fact | **Done (F4).** The assistant's name lives in `identity_ctx`; the user's is owned by the setting. |
| 7 | Report which ladder rung answered | **Done (F5).** `gemini.answered_by()`, and a line printed whenever the ladder substitutes. |
| 8 | Merge the write list into the read list | **Done (F7).** Two lists describing one thing is how a category becomes a silent no-op. |
| 9 | Make typing work for Burmese | **Done (F9).** `typewrite` cannot produce Burmese characters and drops them without a word; the clipboard can. |
| 10 | Make typing say where it typed | **Done (F10).** `Typed into <window>: <text>`, so a mis-targeted type is visible rather than confident. |

Every finding in this report is now closed. `py check_agent.py` checks the behaviour of all of them, so a
later edit cannot quietly undo one.

---

## How to re-run this

The audit was performed by reading the layers and collecting evidence with searches, not by running a tool.
The framework is now available as a skill (`jarvis-agent-audit`), so a future session can repeat it against
a changed codebase rather than starting from a blank page.

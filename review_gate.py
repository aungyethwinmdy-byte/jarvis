"""The review gate — the automated half of the code review.

    py review_gate.py            # static checks + the fast offline suites
    py review_gate.py --static   # static checks only (seconds)
    py review_gate.py --full     # adds check_agent.py (~2 min) and the rest
    py review_gate.py --json     # machine-readable, for a future CI hook

WHY THIS EXISTS

    Every defect in this project's history was a SILENT one. AGENT-AUDIT.md's ten
    findings (F1–F10) and rounds 12–21 of the work log found nothing that threw:
    the loader skipped a broken TOOL without raising, a handler swallowed its
    whole argument dict, a gate declared glyph codes "usable text", a search
    claimed to cover a paper it never read. `check_agent.py` passed 430/430 while
    four of those were live.

    So the gate is written around one question: **if this change is wrong, will
    anything say so?** The static checks below are the ones a machine can answer
    without running the app; the suites are the ones the project already had.

    This script is READ-ONLY. It never writes, deletes, or imports the app.

FAIL AND WARN ARE DIFFERENT THINGS

    FAIL  — unambiguously wrong. No judgement needed; fix it.
    WARN  — a **review trigger**. The pattern is legitimate in some call sites and
            dangerous in others, so a human reads the call site. This is the
            project's own rule: *read the call site before gating* (core/confirm.py).

    The distinction is deliberate. AGENT-AUDIT.md's F6 was first reported by
    `grep -c` and was **wrong in four files out of four** — "counting keywords is
    not evidence". A gate that fails on a keyword trains the reviewer to ignore it,
    so anything judgement-based is a WARN with the reason attached.

WHAT EACH CHECK IS FOR (and the real defect it descends from)

    G1  compile            a syntax error is the one failure that IS loud — keep it that way
    G2  TOOL shape         the loader skips an invalid TOOL silently; this names it
    G3  handler signature  `fn(query="", **_)` swallowed the argument dict — six tools had it
    G4  duplicate tables   a second `_PRICE_ALIASES` was dead code and silently did nothing
    G5  dangerous APIs     `shutil.rmtree` can hang under this machine's trash shim; `shell=True`
                           is how a model-written command becomes a shell script
    G6  `str.isdigit()`    True for ၀-၉, so it never detects a real ASCII digit in Burmese
    G7  literal secrets    `api_keys.json` must be the only home; a key in a .py is a leak
    G8  tool description   a description steers the model harder than the code does
    G9  stale __pycache__  makes an applied fix look unapplied
    G10 memory budget      MEMORY.md is injected every session and has a hard limit

    Checks G2–G8 read the **syntax tree**, not the text, so a pattern inside a
    docstring, a comment, a denylist or a test's own data is not reported. The
    first version of this file scanned raw text and reported `rm -rf` in
    `safe_command.py`'s denylist and in `check_agent.py`'s hostile-command test
    data — three false positives out of three.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTIONS = ROOT / "actions"
CORE = ROOT / "core"
MEMORY = ROOT / ".workbuddy-ai" / "memory"

FAIL = "FAIL"
WARN = "WARN"
INFO = "INFO"

# G10 — MEMORY.md is injected into EVERY session and has a hard limit. Measured
# 2026-10-01: at ~14.9 K chars it was truncated on injection, so the tail of the
# file — the last rules in it — silently stopped reaching the model.
#
# RULES.md and REFERENCE.md are NOT injected; they are read on demand by the
# agent, so their ceilings are a *readability* guard, not a truncation guard, and
# are deliberately looser. Raising one is a judgement call, not a workaround —
# raising MEMORY.md's would be a workaround, and is the one thing not to do.
MEMORY_BUDGET = {"MEMORY.md": 10_000, "RULES.md": 18_000, "REFERENCE.md": 30_000}
_INJECTED = frozenset({"MEMORY.md"})

# G5 — APIs that are wrong HERE, with the reason a reviewer needs. `os.remove` is
# deliberately absent: single-file removal is fine and is used on temp files.
DANGEROUS_CALLS = {
    "shutil.rmtree": "hangs under this machine's trash shim — the undo silently never runs",
    "os.system": "runs a shell string; use subprocess with an argv list",
    "os.popen": "runs a shell string",
    "eval": "executes arbitrary text",
    "exec": "executes arbitrary text — safe only inside a restricted sandbox",
}

# G7 — shapes of a real credential. Deliberately narrow: a false positive here
# wastes a reviewer's time, and these prefixes are unambiguous.
SECRET_RES = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "a Google API key"),
    (re.compile(r"sk-[A-Za-z0-9]{24,}"), "an OpenAI-style key"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{10,}"), "a JWT (a Supabase key)"),
    (re.compile(r"sb[a-z]?_[A-Za-z0-9_\-]{20,}"), "a Supabase key"),
]

# G6 — only files where Burmese text is in play, so `.isdigit()` is a real hazard.
BURMESE_HINT = re.compile(r"[\u1000-\u109f]")

SUITES_FAST = ["check_entities.py", "check_topic.py", "check_sections.py",
               "check_moi.py", "check_moi_index.py"]
SUITES_FULL = ["check_agent.py", "check_startup.py", "check_sources.py"]


class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, check: str, level: str, msg: str, where: str = "") -> None:
        self.items.append({"check": check, "level": level, "msg": msg, "where": where})

    def failures(self) -> int:
        return sum(1 for i in self.items if i["level"] == FAIL)

    def warnings(self) -> int:
        return sum(1 for i in self.items if i["level"] == WARN)

    def has(self, check: str) -> bool:
        return any(i["check"] == check for i in self.items)


def _py_files() -> list[Path]:
    out = list(ROOT.glob("*.py"))
    out += [p for p in ACTIONS.glob("*.py") if not p.name.startswith("_")]
    out += list(CORE.glob("*.py"))
    return sorted(set(out))


def _dotted(node: ast.expr) -> str:
    """`shutil.rmtree` for an Attribute chain, `exec` for a bare Name, else ''."""
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


# ── G1 — compile ──────────────────────────────────────────────────────────────
def g1_compile(rep: Report, sources: dict[Path, str]) -> None:
    for path, src in sources.items():
        try:
            compile(src, str(path), "exec")
        except SyntaxError as e:
            rep.add("G1", FAIL, f"syntax error: {e.msg}", f"{path.name}:{e.lineno}")
    if not rep.has("G1"):
        rep.add("G1", INFO, f"{len(sources)} files compile cleanly")


# ── G2/G3/G8 — the TOOL contract ──────────────────────────────────────────────
def _tool_dict(tree: ast.Module) -> ast.Dict | None:
    """The module-level ``TOOL = {...}`` literal, if there is one."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "TOOL" and isinstance(node.value, ast.Dict):
                    return node.value
    return None


def _dict_get(d: ast.Dict, key: str):
    for k, v in zip(d.keys, d.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _dict_str(d: ast.Dict, key: str) -> str | None:
    v = _dict_get(d, key)
    return v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else None


def g2_g3_g8_tools(rep: Report, trees: dict[Path, ast.Module]) -> None:
    tools = 0
    for path in sorted(ACTIONS.glob("*.py")):
        if path.name.startswith("_"):
            continue
        tree = trees.get(path)
        if tree is None:
            continue
        d = _tool_dict(tree)
        if d is None:
            continue  # a helper module — legitimately not a tool
        tools += 1

        # G2 — the loader skips a malformed TOOL without raising, so name it here.
        missing = [k for k in ("name", "description", "parameters", "handler")
                   if _dict_get(d, k) is None]
        if missing:
            rep.add("G2", FAIL, f"TOOL is missing {', '.join(missing)} — the loader would skip "
                                f"this file with no error", path.name)

        # G3 — the handler must accept `parameters` BY NAME.
        handler_name = _dict_str(d, "handler")
        if handler_name:
            fn = next((n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and n.name == handler_name), None)
            if fn is not None:
                args = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
                if "parameters" not in args:
                    rep.add("G3", FAIL,
                            f"handler `{handler_name}()` has no `parameters` argument — the "
                            f"argument dict is swallowed silently", path.name)

        # G8 — the description is part of the product.
        desc = _dict_str(d, "description") or ""
        if len(desc) < 60:
            rep.add("G8", WARN, f"description is only {len(desc)} chars — it steers the model "
                                f"harder than the code does", path.name)
        if "news" in path.stem and not re.search(r"moi\.gov\.mm|database|newsroom|Supabase",
                                                 desc, re.IGNORECASE):
            rep.add("G8", WARN, "a news tool's description does not name its source", path.name)

    rep.add("G2", INFO, f"{tools} tools checked for shape, signature and description")


# ── G4 — duplicate module-level definitions ───────────────────────────────────
def g4_duplicate_tables(rep: Report, trees: dict[Path, ast.Module]) -> None:
    hits = 0
    for path, tree in trees.items():
        seen: dict[str, int] = {}
        # Top level only: a name assigned in both arms of an `if` is legitimate and
        # lives inside the If node, so it is not counted.
        for node in tree.body:
            names: list[str] = []
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names = [node.name]
            for n in names:
                seen[n] = seen.get(n, 0) + 1
        for name, count in seen.items():
            if count > 1:
                hits += 1
                rep.add("G4", WARN,
                        f"`{name}` is defined at module level {count} times — Python keeps the "
                        f"last, so the earlier one is dead code", path.name)
    if not hits:
        rep.add("G4", INFO, "no duplicated module-level definitions")


# ── G5 — dangerous APIs (a review trigger, not a verdict) ─────────────────────
def g5_dangerous_apis(rep: Report, trees: dict[Path, ast.Module]) -> None:
    hits = 0
    for path, tree in trees.items():
        if path.name == "review_gate.py":
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            dotted = _dotted(node.func)
            if dotted in DANGEROUS_CALLS:
                hits += 1
                rep.add("G5", WARN, f"`{dotted}()` — {DANGEROUS_CALLS[dotted]}",
                        f"{path.name}:{node.lineno}")
            for kw in node.keywords:
                if (kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant) and kw.value.value is True):
                    hits += 1
                    rep.add("G5", WARN,
                            "`shell=True` — the argv becomes a shell command string; safe only "
                            "if every part of it is a literal", f"{path.name}:{node.lineno}")
    if not hits:
        rep.add("G5", INFO, "no dangerous delete/exec APIs")


# ── G6 — `.isdigit()` where Burmese digits are possible ───────────────────────
def g6_isdigit(rep: Report, trees: dict[Path, ast.Module], sources: dict[Path, str]) -> None:
    hits = 0
    for path, tree in trees.items():
        if path.name == "review_gate.py":
            continue
        if not BURMESE_HINT.search(sources.get(path, "")):
            continue  # no Burmese in this file, so the hazard is not present
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "isdigit"):
                hits += 1
                rep.add("G6", WARN,
                        "`.isdigit()` is True for ၀-၉ — use `re.search(r\"[0-9]\")` unless the "
                        "digits were already folded to ASCII", f"{path.name}:{node.lineno}")
    if not hits:
        rep.add("G6", INFO, "no `.isdigit()` in a Burmese-handling file")


# ── G7 — literal secrets ──────────────────────────────────────────────────────
def g7_secrets(rep: Report, sources: dict[Path, str]) -> None:
    hits = 0
    for path, src in sources.items():
        for rx, what in SECRET_RES:
            if rx.search(src):
                hits += 1
                rep.add("G7", FAIL, f"a literal credential ({what}) — secrets belong in "
                                    f"config/api_keys.json", path.name)
    if not hits:
        rep.add("G7", INFO, "no literal credentials in source")


# ── G9 — stale bytecode ───────────────────────────────────────────────────────
def g9_stale_pycache(rep: Report) -> None:
    stale: set[str] = set()
    for py in _py_files():
        cache = py.parent / "__pycache__"
        if not cache.is_dir():
            continue
        for pyc in cache.glob(f"{py.stem}.*.pyc"):
            try:
                if pyc.stat().st_mtime < py.stat().st_mtime:
                    stale.add(py.name)
                    break
            except OSError:
                pass
    if stale:
        shown = ", ".join(sorted(stale)[:8]) + (" …" if len(stale) > 8 else "")
        rep.add("G9", WARN, f"{len(stale)} stale .pyc — a fix can look unapplied: {shown}")
    else:
        rep.add("G9", INFO, "no stale bytecode")


# ── G10 — memory budget ───────────────────────────────────────────────────────
def g10_memory_budget(rep: Report) -> None:
    for name, limit in MEMORY_BUDGET.items():
        p = MEMORY / name
        if not p.is_file():
            rep.add("G10", WARN, f"{name} is missing", str(p))
            continue
        n = len(p.read_text(encoding="utf-8", errors="replace"))
        if n > limit:
            kind = ("injected every session — the overrun is SILENTLY TRUNCATED"
                    if name in _INJECTED else
                    "read on demand — this is a readability ceiling, not truncation")
            rep.add("G10", FAIL if name in _INJECTED else WARN,
                    f"{name} is {n:,} chars (ceiling {limit:,}); {kind}", name)
        else:
            rep.add("G10", INFO, f"{name} {n:,}/{limit:,} chars")


# ── the suites ────────────────────────────────────────────────────────────────
def run_suites(rep: Report, names: list[str]) -> None:
    for name in names:
        script = ROOT / name
        if not script.is_file():
            rep.add("S", WARN, f"{name} not found", name)
            continue
        t0 = time.time()
        try:
            proc = subprocess.run([sys.executable, str(script)], cwd=str(ROOT),
                                  capture_output=True, text=True, timeout=600)
            took = time.time() - t0
            if proc.returncode == 0:
                rep.add("S", INFO, f"{name} passed in {took:.0f}s")
            else:
                tail = (proc.stdout or "").strip().splitlines()[-3:]
                rep.add("S", FAIL, f"{name} exited {proc.returncode} in {took:.0f}s — "
                                   f"last lines: {' | '.join(tail)}", name)
        except subprocess.TimeoutExpired:
            rep.add("S", FAIL, f"{name} timed out after 600s", name)
        except Exception as e:  # noqa: BLE001
            rep.add("S", FAIL, f"{name} could not run: {e}", name)


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="The Mark-LIV review gate (read-only).")
    ap.add_argument("--static", action="store_true", help="static checks only (seconds)")
    ap.add_argument("--full", action="store_true", help="add check_agent.py (~2 min) and the rest")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    rep = Report()
    sources: dict[Path, str] = {}
    trees: dict[Path, ast.Module] = {}
    for p in _py_files():
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            rep.add("G1", FAIL, f"unreadable: {e}", p.name)
            continue
        sources[p] = src
        try:
            trees[p] = ast.parse(src, filename=str(p))
        except SyntaxError as e:
            rep.add("G1", FAIL, f"syntax error: {e.msg}", f"{p.name}:{e.lineno}")

    g1_compile(rep, sources)
    g2_g3_g8_tools(rep, trees)
    g4_duplicate_tables(rep, trees)
    g5_dangerous_apis(rep, trees)
    g6_isdigit(rep, trees, sources)
    g7_secrets(rep, sources)
    g9_stale_pycache(rep)
    g10_memory_budget(rep)

    if not args.static:
        run_suites(rep, SUITES_FAST + (SUITES_FULL if args.full else []))

    if args.json:
        print(json.dumps({"items": rep.items, "failures": rep.failures(),
                          "warnings": rep.warnings()}, ensure_ascii=False, indent=2))
    else:
        order = {FAIL: 0, WARN: 1, INFO: 2}
        for item in sorted(rep.items, key=lambda i: (order[i["level"]], i["check"])):
            mark = {FAIL: "FAIL", WARN: "warn", INFO: " ok "}[item["level"]]
            where = f"  ({item['where']})" if item["where"] else ""
            print(f"[{mark}] {item['check']:<4} {item['msg']}{where}")
        print()
        print(f"{rep.failures()} failure(s), {rep.warnings()} warning(s).")
        if rep.failures():
            print("Not reviewable until every FAIL is resolved or explicitly waived in the "
                  "change record.")
        if rep.warnings():
            print("Every WARN needs a reviewer to read the call site and record the verdict.")

    return 1 if rep.failures() else 0


if __name__ == "__main__":
    sys.exit(main())

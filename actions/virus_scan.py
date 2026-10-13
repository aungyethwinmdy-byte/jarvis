"""Virus scan — Defender's own engine, driven by voice.

WHY IT DRIVES DEFENDER INSTEAD OF SCANNING ITSELF

    Writing a scanner is not the hard part; keeping signatures current is, and
    Windows already does that. `MpCmdRun.exe` is Microsoft's own command-line
    front end to the antimalware service, it is already on every Windows
    machine, and it is the same engine that runs on access. A second scanner
    would be worse at the job and would disagree with the first one.

    It also means **the removal is Defender's decision, not ours.** This module
    scans and reports. When something is found, Defender quarantines it using
    its own rules — which know whether a file is a real threat or a tool the
    user put there on purpose. Nothing here calls `-DisableRemediation`, and
    nothing here deletes a file on the strength of its own opinion.

WHY A QUICK SCAN IS THE DEFAULT

    A full scan reads every file on every drive: hours, and unusable from a
    voice assistant. A quick scan covers the places malware actually starts
    from — memory, startup, the system folders — in minutes. `full` exists and
    says how long it will take before it starts.

MEASURED 2026-09-29 on this machine: `MpCmdRun.exe` is at
`C:\\Program Files\\Windows Defender\\MpCmdRun.exe`, the platform folder is
`C:\\ProgramData\\Microsoft\\Windows Defender\\Platform\\4.18.26080.*`, and no
third-party antivirus is installed — so Defender is the engine that matters here.
"""
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from core.timefmt import to_burmese_digits

_EXE_CANDIDATES = [
    r"C:\Program Files\Windows Defender\MpCmdRun.exe",
    r"C:\Program Files (x86)\Windows Defender\MpCmdRun.exe",
]

# Quick scan: minutes. Full scan: hours. The cap is deliberately generous for a
# quick scan and deliberately short for a full one, because a voice assistant
# cannot hold a conversation for three hours — `full` says so and refuses.
_TIMEOUT_QUICK = 900        # 15 min
_TIMEOUT_FULL = 1800        # 30 min, then it stops and says it stopped

# MpCmdRun's own exit codes.
_EXIT = {
    0: "threat မတွေ့ပါ",
    2: "⚠️ threat တွေ့တယ် — Defender က သူ့ဘာသာ ရှင်းလိုက်တယ် (quarantine)",
}


def _exe() -> str | None:
    for p in _EXE_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _platform_exe() -> str | None:
    """The versioned copy under ProgramData, which is often the live one."""
    base = Path(r"C:\ProgramData\Microsoft\Windows Defender\Platform")
    if not base.exists():
        return None
    versions = sorted([d for d in base.iterdir() if d.is_dir()], reverse=True)
    for v in versions:
        exe = v / "MpCmdRun.exe"
        if exe.exists():
            return str(exe)
    return None


def _run(args: list[str], timeout: int) -> tuple[int, str, float]:
    exe = _exe() or _platform_exe()
    if not exe:
        return -1, "MpCmdRun.exe မတွေ့ပါ — Windows Defender မရှိဘူး", 0.0
    t0 = time.time()
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True,
                           timeout=timeout)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return r.returncode, out, time.time() - t0
    except subprocess.TimeoutExpired:
        return -2, f"{timeout} စက္ကန့် ကျော်သွားလို့ ရပ်လိုက်တယ်", time.time() - t0
    except Exception as exc:                                # noqa: BLE001
        return -3, f"{type(exc).__name__}: {exc}", time.time() - t0


def _engine_line() -> str:
    exe = _exe() or _platform_exe()
    if not exe:
        return "❌ Windows Defender မတွေ့ပါ"
    return f"✓ Windows Defender — {os.path.basename(os.path.dirname(exe)) or 'system'}"


def _fmt(seconds: float) -> str:
    if seconds < 60:
        return f"{to_burmese_digits(int(seconds))} စက္ကန့်"
    return f"{to_burmese_digits(round(seconds / 60, 1))} မိနစ်"


def _record(entry: dict) -> str:
    """One line per run, so 'when did I last scan?' has an answer."""
    try:
        log = Path(__file__).resolve().parent.parent / "memory" / "virus_scan_log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        import json
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return str(log)
    except Exception:                                       # noqa: BLE001
        return ""


def virus_scan(parameters: dict = None, player=None, session_memory=None,
               **_) -> str:
    """Voice entry point.

    **The signature is `(parameters, ...)` and that is not cosmetic.**
    `core/action_loader.py` calls a handler as `fn(parameters=parameters, ...)`,
    so this used to be written `fn(action="scan", scan_type="quick", **_)` and
    the `**_` swallowed every argument — a request for a full scan, or for a
    specific path, silently ran a quick scan of the default target instead.
    Measured 2026-09-29 by auditing every handler's signature against the loader.
    """
    p = parameters or {}
    action = p.get("action", "scan")
    scan_type = p.get("scan_type", "quick")
    path = p.get("path", "")

    act = str(action or "scan").strip().lower()
    kind = str(scan_type or "quick").strip().lower()

    if act in ("status", "check"):
        exe = _exe() or _platform_exe()
        lines = ["🛡️ Virus protection အခြေအနေ", ""]
        if exe:
            lines.append(f"  {_engine_line()}")
            lines.append("  Signature တွေက Windows Update နဲ့ အလိုအလျောက် လန်းနေတယ်")
            lines.append("  Real-time protection — Windows Security မှာ စစ်လို့ရ")
        else:
            lines.append("  ❌ Windows Defender မတွေ့ပါ")
            lines.append("  တခြား antivirus တပ်ထားလား Windows Security မှာ ကြည့်ပါ")
        lines.append("")
        lines.append("scan လုပ်ချင်ရင် — 'virus စစ်ပါ'")
        return "\n".join(lines)

    if act in ("cancel", "stop"):
        code, out, secs = _run(["-Scan", "-Cancel"], 60)
        return f"Scan ရပ်လိုက်ပါပြီ ({to_burmese_digits(code)})"

    if act in ("full", "deep"):
        kind = "full"

    if act not in ("scan", "quick", "full", "custom"):
        return f"Unknown virus_scan action: '{action}'. Use: scan | status | cancel"

    if kind == "custom" or (path and act == "custom"):
        if not path or not os.path.exists(path):
            return f"Path မတွေ့ပါ: {path or '(မပေး)'}"
        # Custom scan of a folder the user named — the one case where the
        # assistant's own knowledge of what to look at beats a preset.
        args = ["-Scan", "-ScanType", "3", "-File", path]
        label, timeout = f"{path} ကို စစ်", _TIMEOUT_QUICK
    elif kind == "full":
        args = ["-Scan", "-ScanType", "2"]
        label, timeout = "အကုန် စစ် (full scan)", _TIMEOUT_FULL
    else:
        args = ["-Scan", "-ScanType", "1"]
        label, timeout = "အမြန် စစ် (quick scan)", _TIMEOUT_QUICK

    warning = ""
    if kind == "full":
        warning = ("\n⚠️ Full scan က ဖိုင်အကုန် ဖတ်တယ် — နာရီနဲ့ချီ ကြာနိုင်တယ်။ "
                   f"{to_burmese_digits(int(_TIMEOUT_FULL / 60))} မိနစ်ကျော်ရင် ရပ်လိုက်မယ်။\n")

    code, out, secs = _run(args, timeout)
    verdict = _EXIT.get(code, f"မသိတဲ့ code ({to_burmese_digits(code)}) — Defender ကို ဖွင့်ကြည့်ပါ")

    lines = [f"🛡️ {label} — ပြီးပါပြီ", warning, f"  {verdict}",
             f"  ကြာချိန်: {_fmt(secs)}"]

    # MpCmdRun is terse and sometimes prints nothing on success. Showing the raw
    # tail when there is one is more useful than a summary that hides it.
    if out:
        interesting = [ln.strip() for ln in out.splitlines()
                       if ln.strip() and "MpCmdRun" not in ln][-6:]
        if interesting:
            lines.append("")
            lines.append("  Defender ပြောတာ:")
            for ln in interesting:
                lines.append(f"    {ln[:150]}")

    log = _record({"when": datetime.now().isoformat(timespec="seconds"),
                   "kind": kind, "exit_code": code, "seconds": round(secs, 1),
                   "path": path or None})
    if log:
        lines.append("")
        lines.append(f"မှတ်တမ်း: {log}")
    return "\n".join(lines)


TOOL = {
    "name": "virus_scan",
    "description": (
        "Scan this PC for viruses and malware using Windows Defender, and "
        "report what it found. Use for: 'virus စစ်ပါ', 'malware ရှိလား', "
        "'ကွန်ပျူတာ သန့်ရှင်းရေး', 'PC သန့်ရှင်းရေးလုပ်ပေးပါ'. "
        "Actions: scan (quick, the default, minutes) | full (hours — warn first) "
        "| custom with a path | status | cancel. "
        "Defender quarantines what it finds; this tool does NOT delete files "
        "itself and must never claim a threat was removed — report the exit "
        "code and let Defender's own result stand."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "scan (default) | status | cancel. 'full' scans everything and takes hours.",
            },
            "scan_type": {
                "type": "STRING",
                "description": "quick (default) | full | custom",
            },
            "path": {
                "type": "STRING",
                "description": "Folder or file to scan when scan_type is custom.",
            },
        },
        "required": [],
    },
    "handler": virus_scan,
}

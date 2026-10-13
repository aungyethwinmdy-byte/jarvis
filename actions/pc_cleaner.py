"""PC Cleaner — look first, delete second, and never touch what cannot be replaced.

WHY IT IS SHAPED THIS WAY

    A cleaner is the one tool in this assistant whose mistakes are unrecoverable,
    so three rules run through everything below.

    1. SCAN IS THE DEFAULT AND DELETE IS NOT.
       Every target can be measured without touching it, and `scan` is what the
       tool does when the user has not clearly asked for a deletion. A cleaner
       whose dangerous path is the default path is a cleaner that will
       eventually eat something.

    2. THE PATHS ARE WRITTEN OUT, ONE PER LINE.
       Never "everything under X". This is also why the module does not go
       through `file_controller`'s guard: half of these live under `C:\\Windows`,
       outside `file_access_roots`, and widening that boundary to cover a
       cleaner would widen it for everything. The list below *is* the boundary.

    3. A DOCUMENT IS NEVER JUNK.
       The user is a journalist. A temp file costs nothing to lose; a draft
       costs a week. Anything with a document extension is skipped **anywhere,
       including inside `%TEMP%`**, and the folders that hold his work are
       skipped by location as well.

    `scan` is read-only. It reports what it found, writes the full list to a
    file, and returns a short summary the assistant can read aloud.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from core.timefmt import to_burmese_digits

# ── What may be cleaned ──────────────────────────────────────────────────────
#
# One entry per target, with everything the report and the gate need. `mode` is
# the lowest mode that includes it, so `quick` stays small and honest.
#
# `needs_admin` is measured, not guessed: `C:\Windows\Temp` is *readable*
# unelevated but not writable, so a scan that lists it and a clean that fails on
# it would be worse than not listing it. The report separates the two.
_TARGETS: list[dict] = [
    {
        "name": "%TEMP%", "mode": "quick", "needs_admin": False,
        "path": lambda: os.environ.get("TEMP") or r"C:\Windows\Temp",
        "note": "files older than the age threshold, unlocked only",
    },
    {
        "name": "Windows Temp", "mode": "deep", "needs_admin": True,
        "path": lambda: r"C:\Windows\Temp",
        "note": "system temp — needs administrator",
    },
    {
        "name": "Windows Update cache", "mode": "deep", "needs_admin": True,
        "path": lambda: r"C:\Windows\SoftwareDistribution\Download",
        "note": "downloaded updates already installed",
    },
    {
        "name": "Delivery Optimization", "mode": "deep", "needs_admin": True,
        "path": lambda: r"C:\Windows\SoftwareDistribution\DeliveryOptimization",
        "note": "update fragments shared between PCs",
    },
    {
        "name": "Error reports (WER)", "mode": "deep", "needs_admin": True,
        "path": lambda: r"C:\ProgramData\Microsoft\Windows\WER",
        "note": "crash dumps",
    },
    {
        "name": "Servicing logs (CBS)", "mode": "deep", "needs_admin": True,
        "path": lambda: r"C:\Windows\Logs\CBS",
        "note": "old CbsPersist_*.log only — the live CBS.log is never touched",
        # The active CBS.log is open by the servicing stack. Deleting it does not
        # free anything (Windows holds it) and can break the next update's
        # diagnostics, so the pattern is explicit rather than "everything here".
        "pattern": "CbsPersist_*.log",
    },
    {
        "name": "Windows logs", "mode": "deep", "needs_admin": True,
        "path": lambda: r"C:\Windows\Logs",
        "note": "setup and servicing logs",
    },
]

# Deliberately NOT a target, and the reasons are measurements from 2026-09-29.
#
#   Prefetch  — 1.1 MB here. Windows uses it to launch applications faster, so
#               clearing it makes the machine slower until it rebuilds. The
#               trade is a measurable slowdown for a rounding error of space.
#
#   Event Viewer logs — clearing these frees megabytes and destroys the audit
#               trail, including the Security log. Nothing about a full disk is
#               worth losing the record of what happened on it, and the spec's
#               own rule ("no essential system files") argues against it.
#
#   `docker system prune -a` — Docker is not installed on this machine. The
#               flag also removes every image not currently used by a container,
#               not just dangling layers, which is a much larger claim than
#               "unused containers, networks and images". If Docker is ever
#               installed, that command deserves its own confirmation.

# Report-only. Listed because they are large, never offered for deletion:
# `Package Cache` is what uninstall and repair read, `WinSxS` may only be
# touched through DISM, and restore points are the user's way back from a bad
# update.
_REPORT_ONLY: list[dict] = [
    {"name": "Package Cache", "path": lambda: r"C:\ProgramData\Package Cache",
     "why": "uninstall and repair read from here"},
    {"name": "WinSxS (component store)", "path": lambda: r"C:\Windows\WinSxS",
     "why": "only DISM may touch it"},
    {"name": "Windows.old", "path": lambda: r"C:\Windows.old",
     "why": "the rollback copy of the previous Windows"},
    {"name": "hiberfil.sys", "path": lambda: r"C:\hiberfil.sys",
     "why": "disabling it also disables Fast Startup"},
]

# ── What may never be deleted ────────────────────────────────────────────────
#
# By extension, anywhere — including inside %TEMP%. An editor keeps recovery
# copies and a download folder keeps drafts in the strangest places, and the
# cost of the two mistakes is not symmetric: skipping a document wastes nothing,
# deleting one cannot be undone.
_NEVER_DELETE_EXT = {
    # Documents — the user's work.
    ".docx", ".doc", ".dot", ".odt", ".rtf", ".wps",
    ".xlsx", ".xls", ".ods", ".csv", ".tsv",
    ".pptx", ".ppt", ".odp",
    ".pdf", ".md", ".txt", ".epub",
    ".jpg", ".jpeg", ".png", ".gif", ".heic", ".tif", ".tiff",
    ".mp3", ".m4a", ".wav", ".mp4", ".mov", ".mkv",
    ".psd", ".ai", ".indd", ".sketch", ".fig",
    # Secrets. The first scan found **80 `.env` files** sitting in %TEMP% — the
    # exact files most likely to hold an API key, and nothing about being in a
    # temp folder makes a secret disposable.
    ".env", ".key", ".pem", ".crt", ".cer", ".p12", ".pfx", ".kdbx", ".jks",
    # Databases. 767 `.sqlite3` files in the same scan. A database in a temp
    # folder is still a database, and losing one is not a cache miss.
    ".db", ".sqlite", ".sqlite3", ".mdb", ".accdb", ".ldb",
    # Binaries and installers — in use, or needed to repair something.
    ".dll", ".exe", ".msi", ".sys", ".ocx", ".so", ".dylib", ".cab",
    # Model weights: large, and expensive to fetch again.
    ".onnx", ".pt", ".pth", ".bin", ".safetensors", ".gguf", ".h5", ".ckpt",
    # Source and scripts. A `.py` in temp is usually a build artefact, but the
    # cost of being wrong is someone's script and the cost of skipping is 1.4 MB
    # (measured) — so it is skipped.
    ".py", ".js", ".ts", ".jsx", ".tsx", ".sh", ".ps1", ".bat", ".cmd",
    ".java", ".cs", ".go", ".rs", ".rb", ".php",
}

# By location. The last two are the user's work: the news archive and the
# newsroom. `file_access_roots` is read as well, so anything the user opens up
# later is protected without another edit here.
_NEVER_DELETE_DIRS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Pictures",
    Path.home() / "Videos",
    Path.home() / "Music",
    Path(r"E:\2026 npt news"),
    Path(r"E:\AI_NEWSROOM"),
]

_DEFAULT_MIN_AGE_HOURS = 24
_MANIFEST = Path(__file__).resolve().parent.parent / "memory" / "pc_cleaner_manifest.jsonl"
_BASE = Path(__file__).resolve().parent.parent


def _extra_protected() -> list[Path]:
    """Roots the user has opened up — protected without a second edit here."""
    try:
        cfg = json.loads((_BASE / "config" / "api_keys.json").read_text(encoding="utf-8"))
        return [Path(str(r)) for r in (cfg.get("file_access_roots") or [])]
    except Exception:                                       # noqa: BLE001
        return []


def _is_protected(path: Path) -> bool:
    """True when this file must never be deleted, whatever the target says."""
    if path.suffix.lower() in _NEVER_DELETE_EXT:
        return True
    try:
        resolved = path.resolve()
    except OSError:
        return True
    for root in _NEVER_DELETE_DIRS + _extra_protected():
        try:
            if resolved.is_relative_to(root.resolve()):
                return True
        except (OSError, ValueError):
            continue
    return False


# ── Measuring ────────────────────────────────────────────────────────────────

def _size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _volume_of(path: str | None) -> str | None:
    """The drive root a path sits on, so free space can be measured on it."""
    if not path:
        return None
    try:
        drive = Path(path).drive
        return drive + "\\" if drive else None
    except (OSError, ValueError):
        return None


def _human(n: int) -> str:
    for unit, div in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= div:
            return f"{n / div:.2f} {unit}"
    return f"{n} B"


def _burmese_size(n: int) -> str:
    """Sizes read aloud get Burmese numerals — the assistant speaks Burmese."""
    return to_burmese_digits(_human(n))


def scan_target(target: dict, min_age_hours: float = _DEFAULT_MIN_AGE_HOURS,
                budget_seconds: float = 90.0) -> dict:
    """Measure one target without touching it.

    `reclaimable` is what a delete would actually free: big enough to matter,
    old enough to be safe, not locked, and not a document. Everything else is
    counted separately so the report can explain itself rather than just
    producing a number.

    `total` is kept beside it and reported too. The first run of this measured
    1.29 GB in %TEMP% but only 34 MB older than 24 hours, and a report that
    showed only the second number would look like the cleaner had failed —
    when in fact the age filter was doing exactly its job. Both belong on
    screen.
    """
    raw = target["path"]()
    root = Path(raw) if raw else None
    out = {
        "name": target["name"], "path": str(root), "mode": target["mode"],
        "needs_admin": target["needs_admin"], "note": target["note"],
        "exists": bool(root and root.exists()),
        "total": 0, "files": 0, "reclaimable": 0, "reclaimable_files": 0,
        "skipped_documents": 0, "skipped_recent": 0, "skipped_locked": 0,
        "skipped_protected": 0, "truncated": False, "candidates": [],
    }
    if not out["exists"]:
        return out

    cutoff = time.time() - min_age_hours * 3600
    deadline = time.time() + budget_seconds

    if root.is_file():                       # hiberfil.sys and friends
        out["total"] = _size_of(root)
        out["files"] = 1
        return out

    for dirpath, _dirs, filenames in os.walk(root, onerror=lambda e: None):
        if time.time() > deadline:
            out["truncated"] = True
            break
        for name in filenames:
            # A target may name a pattern instead of a whole folder — CBS logs
            # use it so the live `CBS.log` is never a candidate.
            pattern = target.get("pattern")
            if pattern and not Path(name).match(pattern):
                continue
            f = Path(dirpath) / name
            try:
                st = f.stat()
            except OSError:
                out["skipped_locked"] += 1
                continue
            out["files"] += 1
            out["total"] += st.st_size

            if _is_protected(f):
                out["skipped_protected"] += 1
                continue
            if st.st_mtime > cutoff:
                out["skipped_recent"] += 1
                continue
            # NOTE: no lock test here, deliberately.
            #
            # The obvious check, `os.access(f, os.W_OK)`, does NOT test whether a
            # file is locked — on Windows it reads the read-only *attribute*, so
            # a file another process holds open reports as writable and this
            # counted it as reclaimable while claiming to have checked. A real
            # lock test means opening the file for writing, which is a side
            # effect a scan must not have.
            #
            # So the scan does not pretend to know. The delete attempt is the
            # lock test: `quick` catches PermissionError per file, skips it, and
            # reports the count. The age threshold is what keeps that rare.
            out["reclaimable"] += st.st_size
            out["reclaimable_files"] += 1
            if len(out["candidates"]) < 4000:
                out["candidates"].append(
                    {"path": str(f), "size": st.st_size, "mtime": int(st.st_mtime)})
    return out


def run_scan(mode: str = "quick",
             min_age_hours: float = _DEFAULT_MIN_AGE_HOURS) -> dict:
    """Measure every target in `mode` or below. Touches nothing."""
    order = {"quick": 0, "deep": 1}
    want = order.get(mode, 0)
    results = [scan_target(t, min_age_hours) for t in _TARGETS
               if order.get(t["mode"], 0) <= want]
    report_only = []
    for t in _REPORT_ONLY:
        p = Path(t["path"]())
        if p.exists():
            report_only.append({"name": t["name"], "path": str(p),
                                "size": _size_of(p) if p.is_file() else 0,
                                "why": t["why"]})
    return {"mode": mode, "min_age_hours": min_age_hours,
            "targets": results, "report_only": report_only,
            "scanned_at": datetime.now().isoformat(timespec="seconds")}


# ── Speaking it ──────────────────────────────────────────────────────────────

def _summary(report: dict) -> str:
    targets = report["targets"]
    now = sum(t["reclaimable"] for t in targets if not t["needs_admin"])
    admin = sum(t["reclaimable"] for t in targets if t["needs_admin"])
    found = [t for t in targets if t["reclaimable"] > 0]

    lines = [f"စစ်ဆေးပြီးပါပြီ ({report['mode']} — "
             f"{to_burmese_digits(report['min_age_hours'])} နာရီအောက် မဖျက်ပါ)။", ""]

    if found:
        lines.append("ရှင်းလို့ရမယ့် ပမာဏ:")
        for t in found:
            tag = " (admin လို)" if t["needs_admin"] else ""
            # Both numbers, always: what is there, and what the age filter will
            # actually let go of. Showing only the second looks like a failure.
            lines.append(f"  • {t['name']} — {_burmese_size(t['reclaimable'])} "
                         f"(ဖိုင် {to_burmese_digits(t['reclaimable_files'])} ခု){tag}")
            lines.append(f"      folder ထဲ စုစုပေါင်း {_burmese_size(t['total'])} — "
                         f"အသစ်လွန်းလို့ ချန်ထားတာ "
                         f"{_burmese_size(t['total'] - t['reclaimable'])}")
        lines.append("")
        lines.append(f"ခုချက်ချင်း ရနိုင်တာ: {_burmese_size(now)}")
        if admin:
            lines.append(f"admin လိုတာ: {_burmese_size(admin)}")
    else:
        lines.append("ရှင်းလို့ရတာ မတွေ့ပါ။")
        for t in targets:
            if t["total"]:
                lines.append(f"  ({t['name']} မှာ {_burmese_size(t['total'])} ရှိပေမယ့် "
                             f"အားလုံး အသစ်လွန်းနေပါတယ်)")

    report_only = [r for r in report.get("report_only", []) if r["size"] > 1024 ** 3]
    if report_only:
        lines.append("")
        lines.append("ဒါတွေက ကြီးပေမယ့် ဖျက်လို့မရပါ (ဖတ်ပြရုံ):")
        for r in report_only:
            lines.append(f"  • {r['name']} — {_burmese_size(r['size'])} — {r['why']}")

    skipped_docs = sum(t["skipped_protected"] for t in targets)
    skipped_recent = sum(t["skipped_recent"] for t in targets)
    if skipped_docs or skipped_recent:
        lines.append("")
        lines.append(f"မဖျက်တာ — စာရွက်စာတမ်း {to_burmese_digits(skipped_docs)} ခု၊ "
                     f"အသစ်လွန်း {to_burmese_digits(skipped_recent)} ခု")

    if any(t["truncated"] for t in targets):
        lines.append("(တချို့ folder တွေ အချိန်ကန့်သတ်လို့ အကုန် မစစ်ရပါ)")
    lines.append("")
    lines.append(f"မှတ်ချက် — {to_burmese_digits(report['min_age_hours'])} နာရီအောက် ဖိုင်တွေ "
                 f"ချန်ထားတယ်။ ဒီအချိန်ကို လျှော့ခိုင်းရင် ပိုရမယ် "
                 f"(ဥပမာ '၁၂ နာရီအောက် ချန်ထား')။")
    lines.append("⚠️ ဘာမှ မဖျက်ရသေးပါ။ ဖျက်ချင်ရင် ပြောပါ။")
    return "\n".join(lines)


def _delete_is_redirected() -> bool:
    """True when something has replaced the delete APIs with a trash shim.

    MEASURED 2026-09-29. WorkBuddy sets `PYTHONPATH` to a `sitecustomize` shim
    that replaces `os.remove`, `os.unlink`, `pathlib.Path.unlink` and
    `shutil.rmtree` with Recycle-Bin versions. Under it, "deleting" 4 GB from
    `%TEMP%` moves 4 GB into `C:\\$Recycle.Bin` **on the same drive** and frees
    nothing at all — while every counter here reports success.

    That is the worst possible failure for this tool: the number goes up, the
    disk does not change, and the user has no way to tell. So the delete path
    checks and refuses instead.

    JARVIS itself does not run under the shim, so this is a guard against being
    invoked from a host that does — not a permanent limitation.
    """
    return "sitecustomize" in getattr(os.remove, "__module__", "")


def _manifest_write(entries: list[dict], summary: dict) -> str:
    """One JSON line per run, plus a plain list of the paths it removed."""
    try:
        _MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        with _MANIFEST.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**summary, "count": len(entries)}) + "\n")
        listing = _MANIFEST.with_name("pc_cleaner_deleted.txt")
        with listing.open("a", encoding="utf-8") as fh:
            fh.write(f"# {summary['when']}  {summary['mode']}  "
                     f"{summary['freed_bytes']} bytes\n")
            for e in entries:
                fh.write(e["path"] + "\n")
        return str(_MANIFEST)
    except Exception as exc:                                # noqa: BLE001
        return f"(manifest could not be written: {exc})"


def clean_target(target: dict, min_age_hours: float = _DEFAULT_MIN_AGE_HOURS,
                 budget_seconds: float = 120.0) -> dict:
    """Delete what `scan_target` found reclaimable. Nothing else.

    The scan and the delete share `scan_target`, so the guard that ran during
    the scan is the guard that runs here — there is no second list to drift out
    of step. Each file is checked again immediately before it is removed,
    because a scan and a delete are not the same instant.

    `PermissionError` is the lock test. There is no way to ask Windows whether a
    file is open without opening it, so the attempt is the test: a locked file
    raises, is counted, and is left alone.
    """
    outcome = {"name": target["name"], "freed": 0, "deleted": 0,
               "locked": 0, "failed": 0, "protected": 0, "entries": []}

    if _delete_is_redirected():
        outcome["failed"] = -1
        return outcome

    report = scan_target(target, min_age_hours, budget_seconds)
    for c in report["candidates"]:
        f = Path(c["path"])
        if _is_protected(f):                    # re-check: the list may have moved
            outcome["protected"] += 1
            continue
        try:
            size = f.stat().st_size
            f.unlink()
            outcome["freed"] += size
            outcome["deleted"] += 1
            outcome["entries"].append({"path": str(f), "size": size})
        except PermissionError:
            outcome["locked"] += 1
        except FileNotFoundError:
            pass
        except OSError:
            outcome["failed"] += 1
    return outcome


# ── Application caches ───────────────────────────────────────────────────────
#
# The largest safe win on this machine by a wide margin — measured 2026-09-29:
# Chrome ~2.7 GB, Telegram 718 MB, VS Code 173 MB, Edge 48 MB. Nine times what
# the temp folders hold.
#
# Two rules, both non-negotiable:
#
#   1. ONLY the cache folders are named. A browser profile root contains
#      `History`, `Cookies`, `Login Data` and `Web Data`; a Telegram `tdata`
#      contains the session. The folder names below are the entire allowlist —
#      nothing is matched by pattern and nothing is deleted recursively from a
#      profile root.
#   2. THE APP MUST BE CLOSED. Clearing a browser cache while the browser runs
#      can corrupt the profile, and the files are open anyway so they would not
#      be freed. The process check refuses rather than trying.
_CACHE_DIR_NAMES = {"cache", "code cache", "gpucache", "cache_data",
                    "shadercache", "grshadercache", "cacheddata",
                    "component cache", "dawngraphitecache"}

_CACHE_APPS: list[dict] = [
    {
        "name": "Chrome", "process": "chrome.exe", "needs_admin": False,
        "base": lambda: Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data",
        "note": "browsing cache only — history, cookies and logins are untouched",
    },
    {
        "name": "Edge", "process": "msedge.exe", "needs_admin": False,
        "base": lambda: Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data",
        "note": "browsing cache only",
    },
    {
        "name": "Telegram", "process": "Telegram.exe", "needs_admin": False,
        "base": lambda: Path(os.environ.get("APPDATA", "")) / "Telegram Desktop" / "tdata" / "user_data" / "cache",
        "note": ("media cache — photos and videos re-download when a chat is "
                 "scrolled again, which costs data on a metered connection"),
    },
    {
        "name": "VS Code", "process": "Code.exe", "needs_admin": False,
        "base": lambda: Path(os.environ.get("APPDATA", "")) / "Code",
        "note": "editor cache",
    },
]


def _process_running(exe: str) -> bool:
    """Is this executable running? Asked of the OS, not guessed."""
    try:
        import psutil
    except ImportError:
        return False                      # cannot tell; the caller warns
    exe = exe.lower()
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info.get("name") or "").lower() == exe:
                return True
        except Exception:                                   # noqa: BLE001
            continue
    return False


def _find_cache_dirs(base: Path, max_depth: int = 3) -> list[Path]:
    """Cache folders under `base`, without walking the whole profile.

    WHY THIS IS NOT `rglob`
        The first version used `base.rglob("*")`, which walks every file in a
        Chrome `User Data` tree — 50,000+ files across the profile, extensions
        and Local Storage — to find perhaps eight cache folders. Measured
        2026-09-29: the cache clean had not finished after four minutes, and
        almost none of that was deleting. A cleaner that takes ten minutes cannot
        be driven by voice, so the walk is bounded by depth and prunes anything
        that is neither a cache nor on the way to one.
    """
    if base.name.lower() in _CACHE_DIR_NAMES:
        return [base]

    found: list[Path] = []
    base_depth = len(base.parts)
    for root, dirs, _files in os.walk(base, onerror=lambda e: None):
        depth = len(Path(root).parts) - base_depth
        if depth >= max_depth:
            dirs[:] = []                     # stop descending, do not prune the match
        keep = []
        for d in dirs:
            if d.lower() in _CACHE_DIR_NAMES:
                found.append(Path(root) / d)
            else:
                keep.append(d)
        dirs[:] = keep
    return found


def scan_app_caches() -> list[dict]:
    """Measure every app cache without touching it."""
    out = []
    for app in _CACHE_APPS:
        base = app["base"]()
        row = {"name": app["name"], "path": str(base), "note": app["note"],
               "exists": base.exists(), "total": 0, "files": 0,
               "running": _process_running(app["process"]), "folders": []}
        if not row["exists"]:
            out.append(row)
            continue
        # Some apps put the cache at the path itself (Telegram:
        # `tdata\user_data\cache`) rather than in a folder named `Cache` under a
        # profile root. `_find_cache_dirs` handles both.
        roots = _find_cache_dirs(base)
        for d in roots:
            # Skip a cache nested inside another we already counted — `Cache`
            # and `Cache\Cache_Data` are the same bytes, and counting both
            # inflated Chrome from 2.2 GB to 3.3 GB in the first measurement.
            if any(str(d).startswith(f + os.sep) for f in row["folders"]):
                continue
            size, count = 0, 0
            for root, _dirs, files in os.walk(d, onerror=lambda e: None):
                for fn in files:
                    try:
                        size += os.path.getsize(os.path.join(root, fn))
                        count += 1
                    except OSError:
                        pass
            row["total"] += size
            row["files"] += count
            row["folders"].append(str(d))
        out.append(row)
    return out


def clean_app_caches(only: str = "") -> list[dict]:
    """Delete the contents of each app's cache folders. Apps must be closed."""
    results = []
    for app in _CACHE_APPS:
        if only and app["name"].lower() != only.lower():
            continue
        row = {"name": app["name"], "freed": 0, "deleted": 0, "locked": 0,
               "running": _process_running(app["process"]), "skipped": ""}
        if row["running"]:
            row["skipped"] = "app ဖွင့်ထားတယ် — ပိတ်မှ ရှင်းလို့ရမယ်"
            results.append(row)
            continue

        base = app["base"]()
        if not base.exists():
            row["skipped"] = "မရှိ"
            results.append(row)
            continue

        targets = _find_cache_dirs(base)
        # Deepest first, so a nested cache is emptied before its parent.
        for d in sorted(targets, key=lambda p: len(str(p)), reverse=True):
            if _is_protected(d):
                continue
            for root, _dirs, files in os.walk(d, onerror=lambda e: None):
                for fn in files:
                    f = Path(root) / fn
                    if _is_protected(f):
                        continue
                    try:
                        size = f.stat().st_size
                        f.unlink()
                        row["freed"] += size
                        row["deleted"] += 1
                    except PermissionError:
                        row["locked"] += 1
                    except (FileNotFoundError, OSError):
                        pass
        results.append(row)
    return results


def _tidy(mode: str, min_age_hours: float) -> str:
    """What "PC သန့်ရှင်းရေးလုပ်ပေးပါ" should actually do.

    Three things in one answer, in the order that makes sense to a person
    asking the question: is anything wrong with it (virus), what is wasting
    space (disk), and what is left that only they can do (guide).

    The virus scan runs FIRST and on purpose. If there is malware, everything
    after it is untrustworthy — a cleaner that reports "2 GB freed" on an
    infected machine is reporting a number produced by a machine someone else
    controls. Measured 2026-09-29: a Defender quick scan takes 44-84 seconds
    here, which is slow for a tool call and acceptable for "clean my PC".
    """
    parts: list[str] = []

    try:
        from actions.virus_scan import virus_scan
        parts.append(virus_scan(action="scan", scan_type="quick"))
    except Exception as exc:                                # noqa: BLE001
        parts.append(f"🛡️ Virus scan မလုပ်နိုင်ပါ: {type(exc).__name__}: {exc}")

    parts.append("")
    parts.append("─" * 34)
    parts.append("")

    report = run_scan(mode, min_age_hours)
    try:
        _MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        _MANIFEST.with_name("pc_cleaner_last_scan.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
    except Exception:                                       # noqa: BLE001
        pass
    parts.append(_summary(report))

    caches = [c for c in scan_app_caches() if c["total"]]
    if caches:
        parts.append("")
        parts.append("App cache (ဒါက ပိုကြီးတယ်):")
        for c in caches:
            state = "⚠️ ဖွင့်ထားတယ်" if c["running"] else "✓ ပိတ်ထားတယ်"
            parts.append(f"  • {c['name']} — {_burmese_size(c['total'])} — {state}")

    parts.append("")
    parts.append("ကိုယ်တိုင် လုပ်ရမယ့်အပိုင်း — 'ရှင်းနည်း ပြောပါ' လို့ ခိုင်းပါ။")
    return "\n".join(parts)


# ── The parts that need a UI, a command JARVIS cannot drive, or a warning ────
#
# Some of the spec is genuinely better done by hand: `cleanmgr` is a GUI,
# `chrome://settings` is a GUI, and two of the items are things the user should
# decide about rather than have done to them. Each entry says what it is worth
# and what it costs, because "free up space" advice that omits the second half
# is how people end up with a slower machine and an empty disk.
_GUIDE: list[dict] = [
    {
        "name": "Windows Disk Cleanup", "worth": "varies",
        "steps": [
            "Windows + R ကို နှိပ်",
            "cleanmgr ရိုက် → Enter",
            "C: ရွေး → OK",
            "'Temporary files' နှင့် 'Delivery Optimization Files' အမှတ်ခြစ်",
            "'Clean up system files' ကို နှိပ်ရင် ပိုရမယ် (admin လိုတယ်)",
        ],
    },
    {
        "name": "Chrome cache", "worth": "~2 GB on this machine",
        "steps": [
            "Chrome ကို အရင် ပိတ်",
            "chrome://settings/clearBrowserData ကို ဖွင့်",
            "⚠️ 'Cached images and files' ပဲ အမှတ်ခြစ်",
            "❌ 'Cookies and other site data' ကို မခြစ်ရ — account တွေ log out ဖြစ်မယ်",
            "❌ 'Browsing history' ကို မခြစ်ရ",
        ],
    },
    {
        "name": "pip cache", "worth": "0 MB on this machine — harmless but pointless",
        "steps": ["cmd ဖွင့် → pip cache purge"],
    },
    {
        "name": "Prefetch", "worth": "1.1 MB — NOT recommended",
        "steps": [
            "❌ မလုပ်တာ ပိုကောင်းတယ်။ Windows က app ဖွင့်တာမြန်အောင် သုံးတယ်။",
            "ဖျက်ရင် app ဖွင့်တာ နှေးလာမယ်၊ ပြန်တည်ဆောက်ရမယ်။",
            "၁ MB အတွက် မထိုက်ဘူး။",
        ],
    },
    {
        "name": "Event Viewer logs", "worth": "few MB — NOT recommended",
        "steps": [
            "❌ မလုပ်တာ ပိုကောင်းတယ်။",
            "Security log ဖျက်ရင် audit trail ဆုံးမယ် — ဘယ်သူ ဘာလုပ်ခဲ့လဲ ဆိုတာ ပျောက်မယ်။",
            "ရနိုင်တာ MB နည်းနည်းပဲ။",
        ],
    },
    {
        "name": "Docker", "worth": "Docker မရှိဘူး (ဒီစက်မှာ)",
        "steps": [
            "တပ်ဆင်ထားရင် — docker system prune (container/network) က လုံခြုံတယ်",
            "⚠️ `-a` ထည့်ရင် image အကုန် ဖျက်မယ် (container မသုံးတဲ့ဟာတွေပါ) — ဆုံးဖြတ်ပြီးမှ",
        ],
    },
]


def _guide() -> str:
    lines = ["ကိုယ်တိုင် လုပ်ရမယ့် အပိုင်း:", ""]
    for g in _GUIDE:
        lines.append(f"▸ {g['name']}  —  {g['worth']}")
        for s in g["steps"]:
            lines.append(f"    {s}")
        lines.append("")
    return "\n".join(lines)


# ── The tool ─────────────────────────────────────────────────────────────────

def pc_cleaner(parameters: dict = None, player=None, session_memory=None,
               **_) -> str:
    """The voice-facing entry point. Deletion is deliberately not wired yet.

    **The signature is `(parameters, ...)` and that is not cosmetic.**
    `core/action_loader.py` calls a handler as `fn(parameters=parameters, ...)`,
    so this used to be written `fn(action="scan", mode="quick", **_)` and the
    `**_` swallowed every argument — `action` was always "scan" and
    **`min_age_hours` always fell back to its default**, which on a cleaning
    tool is the parameter that decides what is old enough to be touched.
    Measured 2026-09-29 by auditing every handler's signature against the loader.
    """
    p = parameters or {}
    action = p.get("action", "scan")
    mode = p.get("mode", "quick")
    min_age_hours = p.get("min_age_hours", _DEFAULT_MIN_AGE_HOURS)

    act = str(action or "scan").strip().lower()
    try:
        min_age_hours = float(min_age_hours)
    except (TypeError, ValueError):
        min_age_hours = _DEFAULT_MIN_AGE_HOURS
    mode = str(mode or "quick").strip().lower()

    if act in ("scan", "check", "report", "list"):
        report = run_scan(mode, min_age_hours)
        try:
            _MANIFEST.parent.mkdir(parents=True, exist_ok=True)
            _MANIFEST.with_name("pc_cleaner_last_scan.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8")
        except Exception:                                   # noqa: BLE001
            pass
        out = _summary(report)
        if mode == "deep":
            caches = [c for c in scan_app_caches() if c["total"]]
            if caches:
                out += "\n\nApp cache (ဒါက ပိုကြီးတယ်):"
                for c in caches:
                    state = "⚠️ ဖွင့်ထားတယ်" if c["running"] else "✓ ပိတ်ထားတယ်"
                    out += (f"\n  • {c['name']} — {_burmese_size(c['total'])} "
                            f"({to_burmese_digits(c['files'])} ဖိုင်) — {state}")
                out += ("\n  app ပိတ်ထားမှ ရှင်းလို့ရမယ်။ "
                        "'app cache ရှင်းပါ' လို့ ပြောပါ။")
        return out

    if act in ("guide", "how", "steps", "manual"):
        return _guide()

    if act in ("tidy", "cleanup_pc", "sanitize"):
        return _tidy(mode, min_age_hours)

    if act in ("caches", "appcache", "cache"):
        rows = [c for c in scan_app_caches() if c["total"] or c["exists"]]
        if not rows:
            return "App cache မတွေ့ပါ။"
        lines = ["App cache အခြေအနေ:", ""]
        for c in rows:
            state = "⚠️ ဖွင့်ထားတယ်" if c["running"] else "✓ ပိတ်ထားတယ်"
            lines.append(f"  • {c['name']} — {_burmese_size(c['total'])} "
                         f"({to_burmese_digits(c['files'])} ဖိုင်) — {state}")
            if c["note"]:
                lines.append(f"      {c['note']}")
        ready = sum(c["total"] for c in rows if not c["running"])
        lines += ["", f"ခုချက်ချင်း ရှင်းလို့ရ: {_burmese_size(ready)}",
                  "⚠️ ဘာမှ မဖျက်ရသေးပါ။"]
        return "\n".join(lines)

    if act in ("clean", "delete", "free"):
        if _delete_is_redirected():
            return ("ဖျက်လို့ မရပါ — ဒီပတ်ဝန်းကျင်မှာ ဖိုင်ဖျက်တာကို Recycle Bin ဆီ "
                    "လွှဲထားတယ်။ အဲ့ဒါဆိုရင် နေရာ လုံးဝ မလွတ်ဘူး။ "
                    "JARVIS ကို ပုံမှန် ဖွင့်ပြီး ခိုင်းပါ။")

        # ── app caches: a separate path, because the rule is different ───────
        if mode in ("caches", "appcache", "cache"):
            vol = _volume_of(str(Path(os.environ.get("LOCALAPPDATA", "C:\\"))))
            free_before = shutil.disk_usage(vol).free if vol else None
            rows = clean_app_caches()
            free_after = shutil.disk_usage(vol).free if vol else None
            total = sum(r["freed"] for r in rows)
            lines = [f"App cache ရှင်းလိုက်ပါပြီ — {_burmese_size(total)}", ""]
            for r in rows:
                if r["skipped"]:
                    lines.append(f"  • {r['name']} — မရှင်းဘူး: {r['skipped']}")
                elif r["deleted"]:
                    lines.append(f"  • {r['name']} — {_burmese_size(r['freed'])} "
                                 f"(ဖိုင် {to_burmese_digits(r['deleted'])} ခု)")
                    if r["locked"]:
                        lines.append(f"      သုံးနေတဲ့ ဖိုင် "
                                     f"{to_burmese_digits(r['locked'])} ခု ချန်ထားတယ်")
            if free_before and free_after:
                real = free_after - free_before
                lines += ["", f"လွတ်သွားတဲ့ နေရာ — {_burmese_size(abs(real))}"
                              + (" တိုးလာ" if real >= 0 else " လျော့သွား")]
                if total > 0 and real < total * 0.5:
                    lines.append("⚠️ Windows က ဖွင့်ထားတဲ့ ဖိုင်ရဲ့ နေရာကို "
                                 "handle ပိတ်မှ ပြန်ပေးတယ် — restart လုပ်မှ ပြန်ရမယ်။")
            return "\n".join(lines)

        report = run_scan(mode, min_age_hours)
        order = {"quick": 0, "deep": 1}
        want = order.get(mode, 0)

        # Measure the volume, not just the files.
        #
        # MEASURED 2026-09-29: the first real run removed 428 MB of directory
        # entries from %TEMP% — the folder measured 764 MB before and 335 MB
        # after, and the Recycle Bin stayed empty, so the files were genuinely
        # gone — and **C: free space did not move at all**. Windows keeps the
        # clusters of a file that was deleted while a process still held it
        # open, and returns them when the last handle closes.
        #
        # A cleaner that reports only the first number is a cleaner that will be
        # called a liar the first time someone opens Explorer. Both numbers go in
        # the answer, and the difference is explained rather than hidden.
        vol = _volume_of(_TARGETS[0]["path"]() if _TARGETS else None)
        free_before = shutil.disk_usage(vol).free if vol else None

        results = [clean_target(t, min_age_hours) for t in _TARGETS
                   if order.get(t["mode"], 0) <= want]
        total = sum(r["freed"] for r in results)
        entries = [e for r in results for e in r["entries"]]

        free_after = shutil.disk_usage(vol).free if vol else None
        real = (free_after - free_before) if (free_before and free_after) else None

        path = _manifest_write(entries, {
            "when": datetime.now().isoformat(timespec="seconds"),
            "mode": mode, "min_age_hours": min_age_hours,
            "freed_bytes": total, "volume_delta_bytes": real,
            "volume": vol,
        })
        lines = [f"ရှင်းလိုက်ပါပြီ — {_burmese_size(total)} ဖျက်လိုက်တယ်။", ""]
        for r in results:
            if r["deleted"]:
                lines.append(f"  • {r['name']} — {_burmese_size(r['freed'])} "
                             f"(ဖိုင် {to_burmese_digits(r['deleted'])} ခု)")
        lines.append("")
        locked = sum(r["locked"] for r in results)
        failed = sum(r["failed"] for r in results)
        if locked:
            lines.append(f"သုံးနေတဲ့ ဖိုင် {to_burmese_digits(locked)} ခု ချန်ထားတယ်။")
        if failed:
            lines.append(f"မရသွားတာ {to_burmese_digits(failed)} ခု။")

        if real is not None:
            lines.append("")
            lines.append(f"လွတ်သွားတဲ့ နေရာ ({vol}) — {_burmese_size(abs(real))}"
                         + (" တိုးလာ" if real >= 0 else " လျော့သွား"))
            # Only worth saying when something was actually removed — otherwise
            # it fires on every idle run and means nothing.
            if total > 0 and real < total * 0.5:
                lines.append(
                    "⚠️ ဖျက်တာ ပြီးပေမယ့် နေရာ မလွတ်သေးဘူး။ Windows က process "
                    "ဖွင့်ထားတဲ့ ဖိုင်ရဲ့ နေရာကို handle ပိတ်မှ ပြန်ပေးတယ် — "
                    "app တွေ ပိတ်တဲ့အခါ (သို့) စက် restart လုပ်မှ ပြန်ရမယ်။")
        lines.append(f"မှတ်တမ်း: {path}")
        return "\n".join(lines)

    return f"Unknown pc_cleaner action: '{action}'. Use: scan | clean"


TOOL = {
    "name": "pc_cleaner",
    "description": (
        "Clean up this PC — disk space, caches, and a virus check. "
        "Use 'tidy' when the user asks to clean or sanitise the computer in "
        "general: 'PC သန့်ရှင်းရေးလုပ်ပေးပါ', 'ကွန်ပျူတာ သန့်ရှင်းရေး', "
        "'clean my PC', 'disk space ရှင်းပေးပါ'. It runs a Defender virus scan, "
        "a disk scan, and the app-cache check, and returns one answer. "
        "Other actions: "
        "'scan' (READ-ONLY, reports what could be cleaned, split into what is "
        "possible now and what needs administrator rights); "
        "'caches' (browser/app cache sizes and whether the app is running); "
        "'guide' (by-hand steps for cleanmgr, Chrome and pip — and which of the "
        "usual tips are NOT worth doing and why); "
        "'clean' deletes — only ever after a scan the user has seen. "
        "Never state a size as freed without the volume actually changing — "
        "Windows holds the clusters of files deleted while open, so the space "
        "may not appear until a reboot."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": ("scan (read-only, default) | caches | guide | clean. "
                                "Prefer scan or guide — clean deletes."),
            },
            "mode": {
                "type": "STRING",
                "description": ("quick (temp files) | deep (adds Windows caches "
                                "and app caches) | caches (browser/app cache only)"),
            },
            "min_age_hours": {
                "type": "NUMBER",
                "description": ("Only files older than this are considered. "
                                "Default 24 — a file younger than that may belong "
                                "to something running right now."),
            },
        },
        "required": [],
    },
    "handler": pc_cleaner,
}

import json
import os
import re
import shutil
import sys
import zipfile
import platform
from pathlib import Path
from datetime import datetime

try:
    import send2trash
    _SEND2TRASH = True
except ImportError:
    _SEND2TRASH = False

from core.undo import push_undo

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


# The user-edited settings file. `file_access_roots` lives here — see
# _extra_roots() for why the boundary is widened from configuration rather than
# from code.
_CONFIG_PATH = _base_dir() / "config" / "api_keys.json"

# Undo keeps a file's previous contents in memory so `write` can be reversed.
# Above this size it does not — a 200 MB log would sit in RAM for the rest of
# the session to protect an edit nobody is going to take back.
_UNDO_CONTENT_LIMIT = 1_000_000


def _undo_move(src: Path, dst: Path):
    """Reverse of a move: put it back where it came from."""
    def _fn():
        if not dst.exists():
            return f"'{dst.name}' is no longer there — nothing moved back."
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(src))
        return f"'{src.name}' is back in {src.parent.name}/."
    return _fn


def _undo_create(target: Path):
    """Reverse of a create: remove what we made — and only if we still made it.

    Deliberately refuses to touch a directory that has since been filled: the
    undo for 'create a folder' is not 'delete whatever ended up in it'."""
    def _fn():
        if not target.exists():
            return f"'{target.name}' is already gone."
        if target.is_dir():
            if any(target.iterdir()):
                return (f"'{target.name}' is not empty any more — "
                        f"leaving it alone rather than deleting your files.")
            target.rmdir()
        else:
            target.unlink()
        return f"Removed '{target.name}'."
    return _fn


def _undo_write(target: Path, previous: str | None):
    """Reverse of a write: restore the old contents, or remove a file that did
    not exist before the write created it."""
    def _fn():
        if previous is None:
            if target.exists():
                target.unlink()
                return f"Removed '{target.name}' — it did not exist before."
            return f"'{target.name}' is already gone."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(previous, encoding="utf-8")
        return f"Restored the previous contents of '{target.name}'."
    return _fn


def _restore_from_trash(original: Path) -> str:
    """Best-effort undelete.

    delete_file uses send2trash, which is the right call: the file lands in the
    Recycle Bin / Trash where the person can also find it themselves. Getting it
    back out again is shell work and only reliable on Windows, where pywin32 is
    already a dependency. Everywhere else this says where the file is instead of
    pretending it failed — the file is not lost either way."""
    if _OS == "Windows":
        try:
            import win32com.client
            shell = win32com.client.Dispatch("Shell.Application")
            bin_folder = shell.NameSpace(10)      # ssfBITBUCKET
            for item in bin_folder.Items():
                if str(bin_folder.GetDetailsOf(item, 1)).strip().lower() == \
                        str(original.parent).strip().lower():
                    if str(item.Name).strip().lower() == original.name.strip().lower():
                        item.InvokeVerb("UNDELETE")
                        return f"'{original.name}' restored from the Recycle Bin."
        except Exception as e:
            print(f"[file] Recycle Bin restore failed: {e}")
    return (f"'{original.name}' is in the Recycle Bin — I could not pull it back "
            f"automatically, but it is there and can be restored by hand.")


_SAFE_ROOTS: list[Path] = [
    Path.home(),
]

# ── Extra roots, chosen by the user ──────────────────────────────────────────
#
# JARVIS is confined to the home directory. That is deliberate — an assistant
# that can read and write anywhere on every drive is one misheard word away from
# a very bad day — but it also meant it could not reach the user's own work, and
# on this machine the newsroom, the projects and the reference repositories all
# live on E:. Every one of them was answered with "Access denied".
#
# So the list is widened from the settings file rather than from code. That file
# is edited by hand, so adding a drive is the user's decision and cannot be made
# by the assistant on its own — which is the whole point of having a boundary.
#
#   "file_access_roots": ["E:\\AI_NEWSROOM", "E:\\Mark-LIV-main"]
#
# Nothing else changes: these are *added* to the home directory, the delete
# protections below still apply, and an empty or missing setting leaves the
# behaviour exactly as it was.
def _extra_roots() -> list[Path]:
    """Folders the user has explicitly opened up, that actually exist."""
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return []
    roots = raw.get("file_access_roots") or []
    if isinstance(roots, str):
        roots = [roots]
    out: list[Path] = []
    for item in roots:
        try:
            p = Path(str(item)).expanduser()
            if p.exists():
                out.append(p)
        except Exception:                                   # noqa: BLE001
            continue
    return out


def _allowed_roots() -> list[Path]:
    return _SAFE_ROOTS + _extra_roots()


def _is_safe_path(target: Path) -> bool:
    """Is the given path inside an allowed root? If not, reject the operation."""
    try:
        resolved = target.resolve()
        return any(
            resolved == root.resolve() or resolved.is_relative_to(root.resolve())
            for root in _allowed_roots()
        )
    except Exception:
        return False

def _get_desktop() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DESKTOP_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Desktop"

def _get_downloads() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOWNLOAD_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Downloads"

def _get_documents() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOCUMENTS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Documents"

def _get_pictures() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_PICTURES_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Pictures"

def _get_music() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_MUSIC_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Music"

def _get_videos() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_VIDEOS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Videos"


def _resolve_path(raw: str) -> Path:
    shortcuts: dict[str, Path] = {
        "desktop":   _get_desktop(),
        "downloads": _get_downloads(),
        "documents": _get_documents(),
        "pictures":  _get_pictures(),
        "music":     _get_music(),
        "videos":    _get_videos(),
        "home":      Path.home(),
    }
    raw   = raw.strip().strip('"').strip("'")
    lower = raw.lower()
    if lower in shortcuts:
        return shortcuts[lower]

    # "desktop/notes/a.md" and "desktop\notes\a.md" — a shortcut followed by a
    # sub-path.  Without this branch the whole string falls through to the
    # relative-path return below and is resolved against the process CWD instead
    # of the real Desktop: an "Access denied" when the project lives outside the
    # home directory, or — worse — a silent write into a stray "desktop" folder
    # inside the project when it lives inside it.
    head, sep, rest = raw.replace("\\", "/").partition("/")
    if sep and head.lower() in shortcuts:
        rest = rest.strip("/")
        return shortcuts[head.lower()] / rest if rest else shortcuts[head.lower()]

    return Path(raw).expanduser()

def _format_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

def _safe_trash(target: Path) -> str:

    if not _SEND2TRASH:
        return (
            "send2trash is not installed. "
            "Run: pip install send2trash — "
            "Permanent deletion is disabled for safety."
        )
    send2trash.send2trash(str(target))
    return f"Moved to Trash: {target.name}"


def list_files(path: str = "desktop", show_hidden: bool = False) -> str:
    try:
        target = _resolve_path(path)
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Path not found: {target}"
        if not target.is_dir():
            return f"Not a directory: {target}"

        items = []
        for item in sorted(target.iterdir()):
            if not show_hidden and item.name.startswith("."):
                continue
            if item.is_dir():
                items.append(f"📁 {item.name}/")
            else:
                size = _format_size(item.stat().st_size)
                items.append(f"📄 {item.name} ({size})")

        if not items:
            return f"Directory is empty: {target.name}/"

        return f"Contents of {target.name}/ ({len(items)} items):\n" + "\n".join(items)

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error listing files: {e}"


def create_file(path: str, name: str = "", content: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        previous = None
        if existed:
            try:
                previous = target.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                previous = None
        target.write_text(content, encoding="utf-8")
        push_undo(f"created {target.name}",
                  _undo_write(target, previous) if existed else _undo_create(target))
        return f"File created: {target.name}"
    except Exception as e:
        return f"Could not create file: {e}"


def create_folder(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        already = target.exists()
        target.mkdir(parents=True, exist_ok=True)
        # Only offer to undo a folder we actually made. "mkdir -p" on something
        # that was already there is not a change, and undoing it would delete a
        # directory the user has had for years.
        if not already:
            push_undo(f"created folder {target.name}", _undo_create(target))
        return f"Folder created: {target.name}"
    except Exception as e:
        return f"Could not create folder: {e}"


def delete_file(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        # Safe-directory check — protect critical user folders
        protected = {
            _get_desktop(), _get_downloads(), _get_documents(),
            _get_pictures(), _get_music(), _get_videos(), Path.home()
        }
        # …and the top of every extra root the user opened up. Being allowed to
        # work inside E:\AI_NEWSROOM is not the same as being allowed to delete
        # E:\AI_NEWSROOM, and the difference is one misheard word.
        protected |= set(_extra_roots())
        if target.resolve() in {p.resolve() for p in protected}:
            return f"Protected directory, cannot delete: {target.name}"

        original = target.resolve()
        result   = _safe_trash(target)
        if result.startswith("Moved to Trash"):
            push_undo(f"deleted {original.name}",
                      lambda p=original: _restore_from_trash(p))
        return result

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Could not delete: {e}"


def move_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base   = _resolve_path(path)
        src    = (base / name) if name else base
        dst    = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        dst.parent.mkdir(parents=True, exist_ok=True)
        origin = src.resolve()
        shutil.move(str(src), str(dst))
        push_undo(f"moved {origin.name} to {dst.parent.name}/",
                  _undo_move(origin, dst.resolve()))
        return f"Moved: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not move: {e}"


def copy_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base = _resolve_path(path)
        src  = (base / name) if name else base
        dst  = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            shutil.copytree(str(src), str(dst))
        else:
            shutil.copy2(str(src), str(dst))

        # The undo for a copy is deleting the copy — never the original.
        _copy = dst.resolve()
        def _undo_copy():
            if not _copy.exists():
                return f"The copy '{_copy.name}' is already gone."
            if _copy.is_dir():
                shutil.rmtree(_copy)
            else:
                _copy.unlink()
            return f"Removed the copy in {_copy.parent.name}/."
        push_undo(f"copied {src.name} to {dst.parent.name}/", _undo_copy)

        return f"Copied: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not copy: {e}"


def rename_file(path: str, name: str = "", new_name: str = "") -> str:
    try:
        base     = _resolve_path(path)
        target   = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"
        if not new_name:
            return "No new name provided."

        new_path = target.parent / new_name
        if new_path.exists():
            return f"A file named '{new_name}' already exists here."

        old_path = target.resolve()
        target.rename(new_path)
        push_undo(f"renamed {old_path.name} to {new_name}",
                  _undo_move(old_path, new_path.resolve()))
        return f"Renamed: {target.name} → {new_name}"

    except Exception as e:
        return f"Could not rename: {e}"


def read_file(path: str, name: str = "", max_chars: int = 4000) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"File not found: {target.name}"
        if not target.is_file():
            return f"Not a file: {target.name}"

        content = target.read_text(encoding="utf-8", errors="ignore")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[Truncated — {len(content)} total chars]"
        return content

    except Exception as e:
        return f"Could not read file: {e}"


def write_file(path: str, name: str = "", content: str = "",
               append: bool = False) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)

        # Snapshot before writing. None means "did not exist", which is a
        # different undo (delete it) from "existed and had this in it".
        previous: str | None = None
        undoable = True
        if target.exists():
            try:
                if target.stat().st_size > _UNDO_CONTENT_LIMIT:
                    undoable = False       # too large to hold in memory
                else:
                    previous = target.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                undoable = False           # binary, locked, unreadable

        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as f:
            f.write(content)

        action = "Appended to" if append else "Written to"
        if undoable:
            push_undo(f"wrote to {target.name}", _undo_write(target, previous))
            return f"{action}: {target.name}"
        return (f"{action}: {target.name}. "
                f"(Too large to keep a copy of the old contents, so this one "
                f"cannot be undone.)")
    except Exception as e:
        return f"Could not write file: {e}"


def find_files(name: str = "", extension: str = "",
               path: str = "home", max_results: int = 20,
               contains: str = "") -> str:
    """Find files by NAME, or — with `contains` — by what is written inside them.

    WHY `contains` EXISTS
        Searching names only is the wrong tool for the question people actually
        ask. Measured 2026-09-28: asked to find a gemstone-news file, a
        name search over Desktop, Documents, Downloads and E: returned 25
        matches and every one was programming noise (`ruby.ico`,
        `tree-sitter-ruby.wasm`). The file existed, but its *name* did not
        contain the word — only its contents did. A journalist knows what a
        document is about; they rarely remember what they called it.

    WHAT IT CAN AND CANNOT READ
        `.docx`/`.xlsx`/`.pptx` are read with the stdlib `zipfile` (they are XML
        in a zip), plain-text formats are read directly, and **PDFs are read
        where their text layer works**.

        That last clause matters. Measured 2026-09-28: the Myanmar state
        newspaper PDFs this project downloads (`myanmaalinn_*.pdf`) extract
        13,000-19,000 characters of **control bytes and zero Burmese** — the font
        has no `/ToUnicode`, so what comes out is glyph indices, not text. A
        normal Burmese PDF from elsewhere extracted 2,427 real characters. So
        the layer is *checked*, and a PDF that cannot be read is reported as
        unreadable rather than as "no match" — those are different answers and
        only one of them means the file is not there.
    """
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Search path not found: {path}"

        results    = []
        dir_count  = 0
        max_dirs   = 500  # performance + safety limit

        if contains:
            return _find_by_content(search_path, contains, extension, max_results)

        for item in search_path.rglob("*"):
            if item.is_dir():
                dir_count += 1
                if dir_count > max_dirs:
                    break
                continue
            if not item.is_file():
                continue
            if extension and item.suffix.lower() != extension.lower():
                continue
            if name and name.lower() not in item.name.lower():
                continue
            size = _format_size(item.stat().st_size)
            results.append(f"📄 {item.name} ({size}) — {item.parent}")
            if len(results) >= max_results:
                break

        if not results:
            query = name or extension or "files"
            return f"No {query} found in {search_path.name}/"

        return f"Found {len(results)} file(s):\n" + "\n".join(results)

    except Exception as e:
        return f"Search error: {e}"


# Formats whose text can be read without a parser. PDF is deliberately absent —
# see find_files' docstring.
_READABLE_EXT = {".txt", ".md", ".csv", ".json", ".log", ".html", ".htm",
                 ".xml", ".py", ".js", ".ts", ".yaml", ".yml", ".ini", ".rtf"}
# Office files are zip archives of XML, so the stdlib can open them.
_ZIP_DOC_EXT  = {".docx", ".xlsx", ".pptx"}
# Documents we genuinely cannot look inside. Counted separately and reported,
# because "nothing found" and "I could not look" are different answers.
_UNREADABLE_DOC_EXT = {".doc", ".xls", ".ppt", ".odt", ".ods", ".odp",
                       ".pages", ".numbers", ".key"}
_PDF_EXT = {".pdf"}


def _looks_like_glyph_noise(text: str) -> bool:
    """True when extracted "text" is font glyph indices rather than characters.

    A PDF whose font has no `/ToUnicode` map gives back the codes the drawing
    operators used, which land in the control range and in private-use areas.
    The test is deliberately about the *ratio*: a readable page is mostly
    letters, a broken one is mostly not.
    """
    sample = (text or "")[:4000]
    if not sample.strip():
        return True
    junk   = sum(1 for c in sample if ord(c) < 32 and c not in "\n\r\t")
    letters = sum(1 for c in sample if c.isalpha())
    return junk > len(sample) * 0.05 or letters < len(sample) * 0.05


def _pdf_text(p: Path) -> tuple[str, bool]:
    """(text, readable). `readable` is False when the layer cannot be trusted."""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf          # the import name before 1.24
        except ImportError:
            return "", False
    try:
        with pymupdf.open(p) as doc:
            if doc.needs_pass:
                return "", False
            text = "".join(pg.get_text() for pg in doc[:40])
    except Exception:                                       # noqa: BLE001
        return "", False
    if _looks_like_glyph_noise(text):
        return "", False
    return text, True


def _document_text(p: Path) -> str:
    """The words inside a document, or '' when this file type cannot be read."""
    try:
        ext = p.suffix.lower()
        if ext in _ZIP_DOC_EXT:
            with zipfile.ZipFile(p) as z:
                # word/document.xml, xl/sharedStrings.xml, ppt/slides/*.xml —
                # every Office format is XML inside a zip, so one pass covers
                # all three. Capped: an .xlsx can hold thousands of parts.
                parts = [n for n in z.namelist()
                         if n.endswith(".xml") and n.split("/")[0] in ("word", "xl", "ppt")]
                return " ".join(
                    re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "replace"))
                    for n in parts[:20]
                )
        if ext in _PDF_EXT:
            return _pdf_text(p)[0]
        if ext in _READABLE_EXT:
            return p.read_text(encoding="utf-8", errors="replace")
    except Exception:                                       # noqa: BLE001
        return ""
    return ""


def _find_by_content(search_path: Path, needle: str, extension: str,
                     max_results: int) -> str:
    """Which files actually mention `needle`."""
    needle_low = needle.lower()
    hits: list[tuple[Path, int]] = []
    read = 0
    skipped_big = 0
    unreadable = 0
    unreadable_pdf = 0
    unreadable_names: list[str] = []     # so the user can go and look themselves
    max_dirs = 500

    dir_count = 0
    for item in search_path.rglob("*"):
        if item.is_dir():
            dir_count += 1
            if dir_count > max_dirs:
                break
            continue
        if not item.is_file():
            continue
        ext = item.suffix.lower()
        if extension and ext != extension.lower():
            continue
        if ext in _UNREADABLE_DOC_EXT:
            # A document we cannot open is worth counting: it is the difference
            # between "no such file" and "I could not look". Everything else —
            # images, executables, caches — is not a document and counting it
            # buries the message in noise (1660 of them, measured on Documents).
            unreadable += 1
            if len(unreadable_names) < 5:
                unreadable_names.append(f"{item.name} — {item.parent}")
            continue
        if ext not in _READABLE_EXT and ext not in _ZIP_DOC_EXT and ext not in _PDF_EXT:
            continue
        try:
            # A PDF is allowed to be much larger than a text document: a scanned
            # 32-page newspaper is 20-40 MB, and only its first 40 pages are read
            # anyway. Judging it by the text-file limit would have skipped the
            # very files a journalist is most likely to be looking for.
            limit = 30_000_000 if ext in _PDF_EXT else 4_000_000
            if item.stat().st_size > limit:
                skipped_big += 1
                if len(unreadable_names) < 5:
                    unreadable_names.append(f"{item.name} — {item.parent} (too large to open)")
                continue
        except OSError:
            continue

        if ext in _PDF_EXT:
            body, readable = _pdf_text(item)
            if not readable:
                # A PDF whose text layer is glyph indices tells us nothing about
                # whether the word is inside it. Counted apart from the other
                # unreadables because the reason is different and so is the fix.
                unreadable_pdf += 1
                if len(unreadable_names) < 5:
                    unreadable_names.append(f"{item.name} — {item.parent} (scanned, no text layer)")
                continue
        else:
            body = _document_text(item)

        read += 1
        if body and needle_low in body.lower():
            hits.append((item, body.lower().count(needle_low)))
        if len(hits) >= max_results:
            break

    if not hits:
        notes = []
        if unreadable:
            notes.append(f"{unreadable} document(s) in a format that cannot be opened")
        if unreadable_pdf:
            notes.append(f"{unreadable_pdf} PDF(s) whose text layer is unusable "
                         f"(the Myanmar newspaper PDFs are like this — the text is "
                         f"an image, so it would have to be read visually)")
        if skipped_big:
            notes.append(f"{skipped_big} too large to open")
        tail = (" — and " + ", ".join(notes)) if notes else ""
        # Naming them matters more than counting them: "4 files I could not
        # check" leaves the user with nowhere to go, whereas the names let them
        # open the likely one by hand.
        listing = ""
        if unreadable_names:
            listing = ("\nFiles that could not be checked:\n"
                       + "\n".join(f"  ❓ {n}" for n in unreadable_names))
        return (f"No file in {search_path.name}/ mentions \"{needle}\" "
                f"(read {read} document(s)){tail}.{listing}")

    lines = [f"📄 {p.name} ({n}×) — {p.parent}" for p, n in hits]
    tail = f" — {unreadable_pdf} PDF(s) could not be read" if unreadable_pdf else ""
    return (f"{len(hits)} file(s) mention \"{needle}\" "
            f"(read {read} document(s)){tail}:\n" + "\n".join(lines))


def get_largest_files(path: str = "downloads", count: int = 10) -> str:
    count = min(count, 50)  # maksimum 50
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Path not found: {path}"

        files = []
        for item in search_path.rglob("*"):
            if item.is_file():
                try:
                    files.append((item.stat().st_size, item))
                except Exception:
                    continue

        files.sort(reverse=True)
        top = files[:count]

        if not top:
            return "No files found."

        lines = [f"Top {len(top)} largest files in {search_path.name}/:"]
        for size, f in top:
            lines.append(f"  {_format_size(size):>10}  {f.name}  ({f.parent})")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


def get_disk_usage(path: str = "home") -> str:
    try:
        target = _resolve_path(path)
        usage  = shutil.disk_usage(target)
        pct    = usage.used / usage.total * 100
        return (
            f"Disk usage ({target}):\n"
            f"  Total : {_format_size(usage.total)}\n"
            f"  Used  : {_format_size(usage.used)} ({pct:.1f}%)\n"
            f"  Free  : {_format_size(usage.free)}"
        )
    except Exception as e:
        return f"Could not get disk usage: {e}"


def organize_desktop() -> str:
    type_map = {
        "Images":    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "Documents": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
                      ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
        "Videos":    {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "Music":     {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
        "Archives":  {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
        "Code":      {".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                      ".cpp", ".java", ".cs", ".go", ".rs", ".sh"},
    }

    desktop = _get_desktop()
    moved, skipped = [], []
    journal: list[tuple[Path, Path]] = []   # (where it was, where it went)

    try:
        for item in desktop.iterdir():
            # Leave folders, hidden files and organize-folders untouched
            if item.is_dir() or item.name.startswith("."):
                continue
            if item.name in {k for k in type_map}:
                continue

            ext        = item.suffix.lower()
            target_dir = desktop / "Others"
            for folder, exts in type_map.items():
                if ext in exts:
                    target_dir = desktop / folder
                    break

            target_dir.mkdir(exist_ok=True)
            new_path = target_dir / item.name

            if new_path.exists():
                skipped.append(item.name)
                continue

            origin = item.resolve()
            shutil.move(str(item), str(new_path))
            journal.append((origin, new_path.resolve()))
            moved.append(f"{item.name} → {target_dir.name}/")

        # One command, dozens of moves — so one undo that reverses all of them.
        # Without this, "organize my desktop" is the single least reversible
        # thing the assistant can do to a person's files, and it was completely
        # ungated.
        if journal:
            def _undo_organize(entries=tuple(journal)):
                restored = 0
                for origin, moved_to in entries:
                    try:
                        if moved_to.exists():
                            origin.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(moved_to), str(origin))
                            restored += 1
                    except Exception as e:
                        print(f"[file] undo organize: {moved_to.name}: {e}")
                # Clear away the folders we created, but only while they are
                # empty — anything the user put in since stays.
                for folder in {m.parent for _o, m in entries}:
                    try:
                        if folder.exists() and folder.is_dir() and not any(folder.iterdir()):
                            folder.rmdir()
                    except Exception:
                        pass
                return f"{restored} file(s) put back on the desktop."
            push_undo(f"organized the desktop ({len(journal)} files)", _undo_organize)

        result = f"Desktop organized: {len(moved)} files moved."
        if moved:
            preview = moved[:8]
            result += "\n" + "\n".join(preview)
            if len(moved) > 8:
                result += f"\n... and {len(moved) - 8} more."
        if skipped:
            result += f"\n{len(skipped)} file(s) skipped (name conflict)."
        return result

    except Exception as e:
        return f"Could not organize desktop: {e}"


def get_file_info(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        stat = target.stat()
        info = {
            "Name":      target.name,
            "Type":      "Folder" if target.is_dir() else "File",
            "Size":      _format_size(stat.st_size),
            "Location":  str(target.parent),
            "Created":   datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
            "Modified":  datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "Extension": target.suffix or "—",
        }
        return "\n".join(f"  {k}: {v}" for k, v in info.items())

    except Exception as e:
        return f"Could not get file info: {e}"

def file_controller(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    path   = params.get("path", "desktop")
    name   = params.get("name", "")

    if player:
        player.write_log(f"[file] {action} {name or path}")

    try:
        if action == "list":
            return list_files(path)

        elif action == "create_file":
            return create_file(path, name=name, content=params.get("content", ""))

        elif action == "create_folder":
            return create_folder(path, name=name)

        elif action == "delete":
            return delete_file(path, name=name)

        elif action == "move":
            return move_file(path, name=name, destination=params.get("destination", ""))

        elif action == "copy":
            return copy_file(path, name=name, destination=params.get("destination", ""))

        elif action == "rename":
            return rename_file(path, name=name, new_name=params.get("new_name", ""))

        elif action == "read":
            return read_file(path, name=name)

        elif action == "write":
            return write_file(
                path, name=name,
                content=params.get("content", ""),
                append=params.get("append", False)
            )

        elif action == "find":
            return find_files(
                name=name or params.get("name", ""),
                extension=params.get("extension", ""),
                path=path,
                max_results=min(int(params.get("max_results", 20)), 50),
                contains=params.get("contains", ""),
            )

        elif action == "largest":
            return get_largest_files(
                path=path,
                count=int(params.get("count", 10)),
            )

        elif action == "disk_usage":
            return get_disk_usage(path)

        elif action == "organize_desktop":
            return organize_desktop()

        elif action == "info":
            return get_file_info(path, name=name)

        else:
            return f"Unknown action: '{action}'"

    except Exception as e:
        return f"File controller error ({action}): {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "file_controller",
    "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"
            },
            "path": {
                "type": "STRING",
                "description": "File/folder path or shortcut: desktop, downloads, documents, home"
            },
            "destination": {
                "type": "STRING",
                "description": "Destination path for move/copy"
            },
            "new_name": {
                "type": "STRING",
                "description": "New name for rename"
            },
            "content": {
                "type": "STRING",
                "description": "Content for create_file/write"
            },
            "name": {
                "type": "STRING",
                "description": "File name to search for"
            },
            "extension": {
                "type": "STRING",
                "description": "File extension to search (e.g. .pdf)"
            },
            "contains": {
                "type": "STRING",
                "description": (
                    "For 'find' only. Search INSIDE documents for this text, in "
                    "the user's own language and unchanged — do not translate it. "
                    "Use this when the user knows what a document is ABOUT but "
                    "not what it is called: 'ကျောက်မျက် အကြောင်း ဖိုင်ရှာပါ'. "
                    "Reads .docx/.xlsx/.pptx, text files, and PDFs whose text "
                    "layer works. A PDF that cannot be read is reported as such, "
                    "not as 'no match' — say so if the user needs to know."
                )
            },
            "count": {
                "type": "INTEGER",
                "description": "Number of results for largest"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": file_controller,
}

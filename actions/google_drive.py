"""Action: google_drive — Google Drive file search, inspection, and download for JARVIS.

Allows JARVIS to:
  1. List recent files in Google Drive ("Drive ထဲက ဖိုင်တွေ ကြည့်ပေးပါ")
  2. Search files by name/keyword ("Drive ထဲ X ဖိုင် ရှာပေးပါ")
  3. Download files from Google Drive to local disk ("Drive ထဲက X ဖိုင် ဒေါင်းလော့ဆွဲပေးပါ")
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from googleapiclient.http import MediaIoBaseDownload

from core.google_auth import get_drive_service
from core.timefmt import to_burmese_digits

_BASE = Path(__file__).resolve().parent.parent
_DOWNLOAD_DIR = _BASE / "downloads" / "google_drive"


def _log(message: str, player=None) -> None:
    print(f"[GoogleDrive] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass


def _format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return ""
    try:
        sb = int(size_bytes)
        if sb < 1024:
            return f"{to_burmese_digits(sb)} B"
        elif sb < 1048576:
            return f"{to_burmese_digits(round(sb / 1024, 1))} KB"
        else:
            return f"{to_burmese_digits(round(sb / 1048576, 1))} MB"
    except Exception:
        return ""


def _list_files(service, query: str = "", max_results: int = 10) -> str:
    """List or search files in Google Drive."""
    q_filter = "trashed = false"
    if query:
        clean_q = query.replace("'", "\\'")
        q_filter += f" and name contains '{clean_q}'"

    try:
        kwargs = {
            "pageSize": max_results,
            "fields": "files(id, name, mimeType, size, webViewLink)",
        }
        if q_filter:
            kwargs["q"] = q_filter
        res = service.files().list(**kwargs).execute()
    except Exception as e:
        return f"⚠️ Google Drive ဖိုင်များ ရှာဖွေရာတွင် အမှားဖြစ်ပေါ်ခဲ့သည်: {e}"

    files = res.get("files", [])
    if not files:
        if query:
            return f"📁 Google Drive ထဲတွင် '{query}' နှင့် ကိုက်ညီသော ဖိုင် မတွေ့ရှိပါ။"
        return "📁 Google Drive ထဲတွင် ဖိုင် မတွေ့ရှိပါ။"

    heading = (
        f"📁 **Google Drive ဖိုင်များ ({to_burmese_digits(len(files))} ခု):**"
        if not query
        else f"🔍 **'{query}' အတွက် ရှာတွေ့သော Drive ဖိုင်များ ({to_burmese_digits(len(files))} ခု):**"
    )
    lines = [heading, ""]

    for idx, f in enumerate(files, 1):
        name = f.get("name", "အမည်မသိ ဖိုင်")
        mime = f.get("mimeType", "")
        size_str = _format_size(f.get("size"))
        link = f.get("webViewLink", "")
        file_id = f.get("id", "")

        type_icon = "📄"
        if "folder" in mime:
            type_icon = "📁"
        elif "image" in mime:
            type_icon = "🖼️"
        elif "pdf" in mime:
            type_icon = "📑"
        elif "spreadsheet" in mime or "sheet" in mime:
            type_icon = "📊"
        elif "presentation" in mime:
            type_icon = "📽️"

        line = f"**{to_burmese_digits(idx)}။** {type_icon} **{name}**"
        if size_str:
            line += f" ({size_str})"
        lines.append(line)
        if link:
            lines.append(f"   🔗 [ဖွင့်ရန် လင့်]({link})")
        lines.append(f"   *(ID: `{file_id}`)*\n")

    return "\n".join(lines).strip()


def _download_file(
    service,
    query: str = "",
    file_id: str = "",
    player=None,
) -> str:
    """Download a file from Google Drive to local downloads/google_drive/ folder."""
    files = []
    if file_id:
        try:
            meta = service.files().get(
                fileId=file_id,
                fields="id, name, mimeType, size",
            ).execute()
            files = [meta]
        except Exception as e:
            return f"⚠️ Google Drive ဖိုင် အချက်အလက်ရယူရာတွင် အမှားဖြစ်ပေါ်ခဲ့သည်: {e}"
    elif query:
        clean_q = query.replace("'", "\\'")
        q_filter = f"trashed = false and name contains '{clean_q}'"
        try:
            res = service.files().list(
                q=q_filter,
                pageSize=5,
                fields="files(id, name, mimeType, size)",
            ).execute()
            files = res.get("files", [])
        except Exception as e:
            return f"⚠️ Google Drive ဖိုင် ရှာဖွေရာတွင် အမှားဖြစ်ပေါ်ခဲ့သည်: {e}"

    if not files:
        target_name = query or file_id or "သတ်မှတ်ထားသော ဖိုင်"
        return f"📁 Google Drive ထဲတွင် '{target_name}' ကို မတွေ့ရှိပါ။"

    target = files[0]
    target_id = target.get("id")
    raw_name = target.get("name", "downloaded_file")
    mime = target.get("mimeType", "")

    if "folder" in mime:
        return f"⚠️ '{raw_name}' သည် Folder ဖြစ်နေသောကြောင့် ဖိုင်အဖြစ် တိုက်ရိုက်ဒေါင်းလော့ဆွဲ၍ မရပါခင်ဗျာ။"

    # Export mapping for Google Workspace native docs
    is_workspace = False
    export_mime = None
    file_name = raw_name

    if mime == "application/vnd.google-apps.document":
        is_workspace = True
        export_mime = "application/pdf"
        if not file_name.lower().endswith(".pdf"):
            file_name += ".pdf"
    elif mime == "application/vnd.google-apps.spreadsheet":
        is_workspace = True
        export_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if not file_name.lower().endswith(".xlsx"):
            file_name += ".xlsx"
    elif mime == "application/vnd.google-apps.presentation":
        is_workspace = True
        export_mime = "application/pdf"
        if not file_name.lower().endswith(".pdf"):
            file_name += ".pdf"

    safe_name = re.sub(r'[\\/*?:"<>|]', "_", file_name)
    _DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = _DOWNLOAD_DIR / safe_name

    _log(f"⬇️ Downloading '{file_name}' from Google Drive ...", player)

    try:
        if is_workspace and export_mime:
            request = service.files().export_media(fileId=target_id, mimeType=export_mime)
        else:
            request = service.files().get_media(fileId=target_id)

        with open(dest_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 512)
            done = False
            while not done:
                _, done = downloader.next_chunk()

    except Exception as e:
        return f"⚠️ Google Drive ဖိုင် ဒေါင်းလော့ဆွဲရာတွင် အမှားဖြစ်ပေါ်ခဲ့သည်: {e}"

    final_size = dest_path.stat().st_size if dest_path.exists() else 0
    size_label = _format_size(final_size)

    match_info = ""
    if not file_id and len(files) > 1:
        match_info = f"\n*(ကိုက်ညီသော ဖိုင် {to_burmese_digits(len(files))} ခုအနက် '{raw_name}' ကို ဒေါင်းလော့ဆွဲယူထားပါသည်)*"

    return (
        f"✅ Google Drive မှ **'{raw_name}'** ကို အောင်မြင်စွာ ဒေါင်းလော့ဆွဲယူပြီးပါပြီ။\n"
        f"📁 ဖိုင်အရွယ်အစား: {size_label}\n"
        f"💾 သိမ်းဆည်းထားသည့် နေရာ: `downloads/google_drive/{safe_name}`{match_info}"
    )


def google_drive(parameters: dict | None = None, player=None, session_memory=None, **_) -> str:
    """Main voice/API entry point for Google Drive operations."""
    params = parameters or {}
    action = params.get("action", "").strip().lower()
    query = params.get("query", "").strip()
    file_id = params.get("file_id", "").strip()
    max_results = int(params.get("max_results", 10))

    service, err = get_drive_service()
    if not service:
        return err

    if action in ("download", "get"):
        text = _download_file(service, query=query, file_id=file_id, player=player)
    else:
        text = _list_files(service, query=query, max_results=max_results)

    if session_memory:
        try:
            session_memory.set_last_search(
                query=f"google_drive {action or 'search'} {query or file_id}",
                response=text,
            )
        except Exception:
            pass

    return text


def run(params: dict | None = None) -> str:
    return google_drive(params)


TOOL = {
    "name": "google_drive",
    "description": (
        "Search, list, and download files from the user's Google Drive. "
        "Use action='search' to list or find files: 'Drive ထဲက ဖိုင်တွေ ကြည့်ပေးပါ', "
        "'Drive ထဲ သတင်းစာ ဖိုင် ရှာပေးပါ', 'list files in drive'. "
        "Use action='download' to download a file from Google Drive to local disk: "
        "'Drive ထဲက သတင်းစာဖိုင် ဒေါင်းလော့ဆွဲပေးပါ', 'Drive က [ဖိုင်အမည်] ဒေါင်းလော့ဆွဲပါ', "
        "'download file from google drive'. "
        "Downloaded files are saved in 'downloads/google_drive/'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'search' (default) to list/search files, or 'download' to download a file to the computer.",
            },
            "query": {
                "type": "STRING",
                "description": "File name or search keyword to filter or download.",
            },
            "file_id": {
                "type": "STRING",
                "description": "Optional specific Google Drive file ID if downloading by exact ID.",
            },
            "max_results": {
                "type": "INTEGER",
                "description": "Maximum number of files to return when searching (default: 10).",
            },
        },
        "required": [],
    },
    "handler": google_drive,
}

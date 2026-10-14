"""Action: google_drive — Google Drive file search and inspection for JARVIS.

Allows JARVIS to:
  1. List recent files in Google Drive ("Drive ထဲက ဖိုင်တွေ ကြည့်ပေးပါ")
  2. Search files by name/keyword ("Drive ထဲ X ဖိုင် ရှာပေးပါ")
"""
from __future__ import annotations

from typing import Any

from core.google_auth import get_drive_service
from core.timefmt import to_burmese_digits


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
            "fields": "files(id, name, mimeType, webViewLink)",
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

    heading = f"📁 **Google Drive ဖိုင်များ ({to_burmese_digits(len(files))} ခု):**" if not query else f"🔍 **'{query}' အတွက် ရှာတွေ့သော Drive ဖိုင်များ ({to_burmese_digits(len(files))} ခု):**"
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


def google_drive(parameters: dict | None = None, player=None, session_memory=None, **_) -> str:
    """Main voice/API entry point for Google Drive operations."""
    params = parameters or {}
    query = params.get("query", "").strip()
    max_results = int(params.get("max_results", 10))

    service, err = get_drive_service()
    if not service:
        return err

    return _list_files(service, query=query, max_results=max_results)


def run(params: dict | None = None) -> str:
    return google_drive(params)


TOOL = {
    "name": "google_drive",
    "description": (
        "Search and list files in the user's Google Drive. "
        "Use this tool when the user asks about Google Drive files: "
        "'Drive ထဲက ဖိုင်တွေ ကြည့်ပေးပါ', 'Drive ထဲ X ဖိုင် ရှာပေးပါ', "
        "'list files in google drive', 'search drive files'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Optional search term to filter files by name.",
            },
            "max_results": {
                "type": "INTEGER",
                "description": "Maximum number of files to return (default: 10).",
            },
        },
        "required": [],
    },
    "handler": google_drive,
}

"""Action: google_workspace — Google Calendar & Tasks integration for JARVIS.

Allows JARVIS to:
  1. Check upcoming calendar events ("ဒီနေ့ ဘာအစီအစဉ်ရှိလဲ", "ပြက္ခဒိန် စစ်ပေးပါ")
  2. Add calendar events ("မနက်ဖြန် မနက် ၉ နာရီ Meeting ထည့်ပေးပါ")
  3. List to-do tasks ("မှတ်ထားတဲ့ Task တွေ ကြည့်ပေးပါ")
  4. Add to-do tasks ("Task အသစ် မှတ်ပေးပါ")
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.google_auth import get_calendar_service, get_tasks_service
from core.timefmt import burmese_date, now_mmt, to_burmese_digits


def _list_calendar_events(service, max_results: int = 5) -> str:
    """List upcoming events from the primary calendar."""
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        events_result = service.events().list(
            calendarId="primary",
            timeMin=now_iso,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except Exception as e:
        return f"⚠️ Google Calendar စစ်ဆေးရာတွင် အမှားဖြစ်ပေါ်ခဲ့သည်: {e}"

    events = events_result.get("items", [])
    if not events:
        return "📅 လက်ရှိတွင် လာမည့် အစီအစဉ်သစ် (Upcoming events) မရှိသေးပါ။"

    lines = [f"📅 **လာမည့် အစီအစဉ်များ ({to_burmese_digits(len(events))} ခု):**", ""]
    for idx, ev in enumerate(events, 1):
        summary = ev.get("summary", "(ခေါင်းစဉ် မရှိပါ)")
        start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
        desc = ev.get("description", "")
        lines.append(f"**{to_burmese_digits(idx)}။** 📌 **{summary}**")
        lines.append(f"   အချိန်: `{start}`")
        if desc:
            lines.append(f"   အသေးစိတ်: {desc[:100]}")
        lines.append("")

    return "\n".join(lines).strip()


def _add_calendar_event(service, summary: str, start_time: str, end_time: str = "", description: str = "") -> str:
    """Add an event to the primary calendar."""
    if not summary:
        return "⚠️ ထည့်သွင်းလိုသော အစီအစဉ် ခေါင်းစဉ် (Summary) ပြောပြပေးပါ။"
    if not start_time:
        return "⚠️ စတင်မည့် အချိန် (ISO format သို့မဟုတ် YYYY-MM-DD HH:MM) လိုအပ်ပါသည်။"

    body: dict[str, Any] = {
        "summary": summary,
        "description": description or "",
    }
    # If date only
    if len(start_time) == 10:
        body["start"] = {"date": start_time}
        body["end"] = {"date": end_time or start_time}
    else:
        body["start"] = {"dateTime": start_time}
        body["end"] = {"dateTime": end_time or start_time}

    try:
        created = service.events().insert(calendarId="primary", body=body).execute()
        link = created.get("htmlLink", "")
        return f"✅ Google Calendar တွင် အစီအစဉ် အသစ် ထည့်သွင်းပြီးပါပြီ!\n📌 ခေါင်းစဉ်: {summary}\n⏰ အချိန်: {start_time}" + (f"\n🔗 [ပြက္ခဒိန်တွင် ကြည့်ရန်]({link})" if link else "")
    except Exception as e:
        return f"⚠️ Calendar အစီအစဉ် ထည့်သွင်းခြင်း မအောင်မြင်ပါ: {e}"


def _list_tasks(service, max_results: int = 10) -> str:
    """List pending tasks from default task list."""
    try:
        res = service.tasks().list(tasklist="@default", maxResults=max_results, showCompleted=False).execute()
    except Exception as e:
        return f"⚠️ Google Tasks စစ်ဆေးရာတွင် အမှားဖြစ်ပေါ်ခဲ့သည်: {e}"

    items = res.get("items", [])
    if not items:
        return "📝 လက်ရှိတွင် မပြီးပြတ်သေးသော Task (လုပ်ငန်းစဉ်) မရှိပါ။ အားလုံး ပြီးစီးနေပါသည်။"

    lines = [f"📝 **လက်ရှိ Tasks စာရင်း ({to_burmese_digits(len(items))} ခု):**", ""]
    for idx, t in enumerate(items, 1):
        title = t.get("title", "(အမည်မရှိ)")
        notes = t.get("notes", "")
        lines.append(f"**{to_burmese_digits(idx)}။** ◻️ {title}")
        if notes:
            lines.append(f"   📝 {notes[:100]}")
    return "\n".join(lines).strip()


def _add_task(service, title: str, notes: str = "") -> str:
    """Add a new task."""
    if not title:
        return "⚠️ မှတ်သားလိုသော Task ခေါင်းစဉ် ပြောပြပေးပါ။"
    body = {"title": title}
    if notes:
        body["notes"] = notes
    try:
        created = service.tasks().insert(tasklist="@default", body=body).execute()
        return f"✅ Google Tasks တွင် အသစ်မှတ်သားပြီးပါပြီ: **{title}**"
    except Exception as e:
        return f"⚠️ Task ထည့်သွင်းခြင်း မအောင်မြင်ပါ: {e}"


def google_workspace(parameters: dict | None = None, player=None, session_memory=None, **_) -> str:
    """Main voice/API entry point for Google Calendar and Tasks."""
    params = parameters or {}
    action = params.get("action", "list_events").strip().lower()
    summary = params.get("summary") or params.get("title") or ""
    start_time = params.get("start_time", "").strip()
    end_time = params.get("end_time", "").strip()
    description = params.get("description") or params.get("notes") or ""
    max_results = int(params.get("max_results", 5))

    if "task" in action:
        task_service, err = get_tasks_service()
        if not task_service:
            return err
        if action in ("add_task", "create_task", "new_task"):
            return _add_task(task_service, title=summary, notes=description)
        return _list_tasks(task_service, max_results=max_results)
    else:
        cal_service, err = get_calendar_service()
        if not cal_service:
            return err
        if action in ("add_event", "create_event", "schedule"):
            return _add_calendar_event(cal_service, summary=summary, start_time=start_time, end_time=end_time, description=description)
        return _list_calendar_events(cal_service, max_results=max_results)


def run(params: dict | None = None) -> str:
    return google_workspace(params)


TOOL = {
    "name": "google_workspace",
    "description": (
        "Manage Google Calendar events and Google Tasks (to-do lists and notes). "
        "Use this tool when the user asks about schedules, appointments, or tasks: "
        "'ဒီနေ့ ဘာအစီအစဉ်ရှိလဲ', 'ပြက္ခဒိန် စစ်ပေးပါ', 'calendar events', "
        "'အစီအစဉ်သစ် ထည့်ပေးပါ', 'tasks တွေ ကြည့်ပေးပါ', 'task အသစ် မှတ်ပေးပါ'. "
        "Actions: 'list_events' (default), 'add_event', 'list_tasks', 'add_task'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Action: 'list_events', 'add_event', 'list_tasks', or 'add_task'.",
            },
            "summary": {
                "type": "STRING",
                "description": "Event summary or task title.",
            },
            "start_time": {
                "type": "STRING",
                "description": "Event start time (ISO string or YYYY-MM-DD HH:MM).",
            },
            "end_time": {
                "type": "STRING",
                "description": "Event end time (ISO string or YYYY-MM-DD HH:MM).",
            },
            "description": {
                "type": "STRING",
                "description": "Event description or task notes.",
            },
            "max_results": {
                "type": "INTEGER",
                "description": "Maximum number of items to return (default: 5).",
            },
        },
        "required": [],
    },
    "handler": google_workspace,
}

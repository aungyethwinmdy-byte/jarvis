"""Action: gmail_action — Gmail integration for JARVIS.

Allows JARVIS to:
  1. Check unread emails ("ဂျာဗစ် မေးလ်အသစ်တွေ ဝင်လား", "အီးမေးလ် စစ်ပေးပါ")
  2. Read full email content ("ဒီအီးမေးလ် အပြည့်အစုံ ဖတ်ပြပါ")
  3. Search emails by sender, subject, or query ("X ဆီက အီးမေးလ် ရှိလား")
  4. Send emails ("အီးမေးလ် ပို့ပေးပါ")
"""
from __future__ import annotations

import base64
import email.header
import re
from email.mime.text import MIMEText
from typing import Any, Optional

from core.google_auth import get_gmail_service
from core.timefmt import to_burmese_digits


def _decode_mime_header(header_value: str) -> str:
    """Decode RFC 2047 encoded email headers."""
    if not header_value:
        return ""
    try:
        decoded_parts = email.header.decode_header(header_value)
        out = []
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                out.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                out.append(str(part))
        return " ".join(out).strip()
    except Exception:
        return str(header_value).strip()


def _get_header(headers: list[dict], name: str) -> str:
    """Find a specific header value from Gmail message payload headers."""
    target = name.lower()
    for h in headers:
        if h.get("name", "").lower() == target:
            return _decode_mime_header(h.get("value", ""))
    return ""


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from Gmail message payload."""
    body_data = ""

    if "parts" in payload:
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    body_data = data
                    break
            elif "parts" in part:
                sub_body = _extract_body(part)
                if sub_body:
                    return sub_body

    if not body_data and payload.get("body", {}).get("data"):
        body_data = payload["body"]["data"]

    if body_data:
        try:
            raw_bytes = base64.urlsafe_b64decode(body_data + "==")
            text = raw_bytes.decode("utf-8", errors="replace")
            # Strip excessive whitespace / HTML tags if any
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text
        except Exception:
            return ""

    return ""


def _check_unread(service, max_results: int = 5) -> str:
    """Check for new/unread incoming emails."""
    try:
        res = service.users().messages().list(
            userId="me",
            q="is:unread",
            maxResults=max_results,
        ).execute()
    except Exception as e:
        return f"⚠️ အီးမေးလ်များ စစ်ဆေးရာတွင် အမှားတစ်ခု ဖြစ်ပေါ်ခဲ့သည်: {e}"

    messages = res.get("messages", [])
    if not messages:
        return "📬 လက်ရှိတွင် မဖတ်ရသေးသော အီးမေးလ်အသစ် (Unread email) မရှိပါ။ အားလုံး ရှင်းလင်းနေပါသည်။"

    total = len(messages)
    lines = [f"📬 **မဖတ်ရသေးသော အီးမေးလ်အသစ် {to_burmese_digits(total)} စောင် တွေ့ရှိပါသည်:**", ""]

    for idx, m in enumerate(messages, 1):
        try:
            detail = service.users().messages().get(
                userId="me",
                id=m["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = detail.get("payload", {}).get("headers", [])
            sender = _get_header(headers, "From") or "အမည်မသိ ပေးပို့သူ"
            subject = _get_header(headers, "Subject") or "(ခေါင်းစဉ် မပါရှိပါ)"
            date_str = _get_header(headers, "Date")
            snippet = detail.get("snippet", "")

            lines.append(f"**{to_burmese_digits(idx)}။ စာပို့သူ:** {sender}")
            lines.append(f"   **ခေါင်းစဉ်:** {subject}")
            if date_str:
                lines.append(f"   **ရက်စွဲ:** {date_str}")
            if snippet:
                lines.append(f"   **အကျဉ်းချုပ်:** {snippet[:150]}{'…' if len(snippet) > 150 else ''}")
            lines.append(f"   *(ID: `{m['id']}`)*\n")
        except Exception as err:
            lines.append(f"**{to_burmese_digits(idx)}။** (မေးလ်ဖတ်၍ မရပါ: {err})\n")

    lines.append("ℹ️ အီးမေးလ်တစ်စောင်၏ အကြောင်းအရာ အပြည့်အစုံကို ဖတ်ရှုလိုပါက 'နံပါတ် (၁) အီးမေးလ် အပြည့်အစုံ ဖတ်ပြပါ' ဟု ပြောနိုင်ပါသည်။")
    return "\n".join(lines).strip()


def _read_email(service, message_id: str) -> str:
    """Read the full content of a specific email by ID."""
    if not message_id:
        return "⚠️ ဖတ်ရှုလိုသော အီးမေးလ် ID မပါရှိပါ။"

    try:
        msg = service.users().messages().get(
            userId="me",
            id=message_id,
            format="full",
        ).execute()
    except Exception as e:
        return f"⚠️ အီးမေးလ် (ID: {message_id}) ကို ဖတ်ရှု၍ မရပါ: {e}"

    headers = msg.get("payload", {}).get("headers", [])
    sender = _get_header(headers, "From")
    subject = _get_header(headers, "Subject")
    date_str = _get_header(headers, "Date")
    body = _extract_body(msg.get("payload", {})) or msg.get("snippet", "")

    lines = [
        "📧 **အီးမေးလ် အပြည့်အစုံ**",
        f"**စာပို့သူ:** {sender}",
        f"**ခေါင်းစဉ်:** {subject}",
        f"**ရက်စွဲ:** {date_str}",
        "",
        "**အကြောင်းအရာ:**",
        body[:1500] + ("\n...(အကြောင်းအရာ ရှည်လျားသဖြင့် အကျဉ်းချုပ်ထားပါသည်)" if len(body) > 1500 else ""),
    ]
    return "\n".join(lines)


def _search_emails(service, query: str, max_results: int = 5) -> str:
    """Search emails with a custom query."""
    if not query:
        return "⚠️ ရှာဖွေလိုသော အကြောင်းအရာ သို့မဟုတ် စာပို့သူ အမည် ပြောပြပေးပါ။"

    try:
        res = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()
    except Exception as e:
        return f"⚠️ အီးမေးလ် ရှာဖွေရာတွင် အမှားဖြစ်ပေါ်ခဲ့သည်: {e}"

    messages = res.get("messages", [])
    if not messages:
        return f"🔍 '{query}' နှင့် သက်ဆိုင်သော အီးမေးလ် ရှာမတွေ့ပါ။"

    lines = [f"🔍 **'{query}' အတွက် ရှာတွေ့သော အီးမေးလ် {to_burmese_digits(len(messages))} စောင်:**", ""]
    for idx, m in enumerate(messages, 1):
        try:
            detail = service.users().messages().get(
                userId="me",
                id=m["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = detail.get("payload", {}).get("headers", [])
            sender = _get_header(headers, "From")
            subject = _get_header(headers, "Subject")
            snippet = detail.get("snippet", "")
            lines.append(f"**{to_burmese_digits(idx)}။** {subject}")
            lines.append(f"   From: {sender} | ID: `{m['id']}`")
            if snippet:
                lines.append(f"   {snippet[:100]}…\n")
        except Exception:
            continue

    return "\n".join(lines).strip()


def _send_email(service, to: str, subject: str, body: str) -> str:
    """Send an email."""
    if not to:
        return "⚠️ လက်ခံမည့်သူ၏ အီးမေးလ်လိပ်စာ (Recipient) ထည့်သွင်းပေးပါ။"
    if not subject:
        subject = "(No Subject)"
    if not body:
        return "⚠️ ပေးပို့မည့် အီးမေးလ် အကြောင်းအရာ (Body) ထည့်သွင်းပေးပါ။"

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject

    raw_msg = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        sent = service.users().messages().send(
            userId="me",
            body={"raw": raw_msg},
        ).execute()
        return f"✅ အီးမေးလ် အောင်မြင်စွာ ပို့ပြီးပါပြီ!\n📨 သို့: {to}\n📌 ခေါင်းစဉ်: {subject}\n*(Message ID: `{sent['id']}`)*"
    except Exception as e:
        return f"⚠️ အီးမေးလ် ပေးပို့ခြင်း မအောင်မြင်ပါ: {e}"


def gmail_action(parameters: dict | None = None, player=None, session_memory=None, **_) -> str:
    """Main voice/API entry point for Gmail operations."""
    params = parameters or {}
    action = params.get("action", "check_unread").strip().lower()
    query = params.get("query", "").strip()
    message_id = params.get("message_id", "").strip()
    to = params.get("to", "").strip()
    subject = params.get("subject", "").strip()
    body = params.get("body", "").strip()
    max_results = int(params.get("max_results", 5))

    service, err = get_gmail_service()
    if not service:
        return err

    if action in ("check_unread", "unread", "inbox", "new", "list"):
        return _check_unread(service, max_results=max_results)
    elif action in ("read", "read_email", "detail", "get"):
        return _read_email(service, message_id=message_id)
    elif action in ("search", "find"):
        return _search_emails(service, query=query, max_results=max_results)
    elif action in ("send", "send_email"):
        return _send_email(service, to=to, subject=subject, body=body)
    else:
        return _check_unread(service, max_results=max_results)


def run(params: dict | None = None) -> str:
    return gmail_action(params)


TOOL = {
    "name": "gmail_action",
    "description": (
        "Interact with the user's Gmail account. "
        "Use this tool whenever the user asks about emails: "
        "'မေးလ်အသစ် ဝင်လား', 'အီးမေးလ် စစ်ပေးပါ', 'check my emails', "
        "'unread emails', 'read email', 'search email', 'send email'. "
        "Actions: 'check_unread' (default, lists new unread emails), "
        "'read_email' (reads email body by message_id), 'search' (searches by query), "
        "'send_email' (sends email to recipient)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "The action to perform: 'check_unread', 'read_email', 'search', or 'send_email'.",
            },
            "query": {
                "type": "STRING",
                "description": "Search query for searching emails (e.g. sender, subject keyword).",
            },
            "message_id": {
                "type": "STRING",
                "description": "ID of the message to read in detail.",
            },
            "to": {
                "type": "STRING",
                "description": "Recipient email address for send_email.",
            },
            "subject": {
                "type": "STRING",
                "description": "Subject of the email to send.",
            },
            "body": {
                "type": "STRING",
                "description": "Body text of the email to send.",
            },
            "max_results": {
                "type": "INTEGER",
                "description": "Maximum number of emails to retrieve (default: 5).",
            },
        },
        "required": [],
    },
    "handler": gmail_action,
}

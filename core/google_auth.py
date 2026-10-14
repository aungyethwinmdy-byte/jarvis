"""Google Services OAuth2 authentication manager for JARVIS.

Handles token persistence, auto-refresh, and initial OAuth login for:
  - Gmail API
  - Google Drive API
  - Google Calendar API
  - Google Tasks API

Credentials file:
  config/credentials.json (or config/google_credentials.json)
Token file:
  config/google_token.json
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger("GoogleAuth")

_BASE_DIR = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _BASE_DIR / "config"
_TOKEN_FILE = _CONFIG_DIR / "google_token.json"

_CREDENTIAL_CANDIDATES = (
    _CONFIG_DIR / "credentials.json",
    _CONFIG_DIR / "google_credentials.json",
    _CONFIG_DIR / "client_secret.json",
)

# Unified scopes for personal Google services
SCOPES = [
    # Gmail: read emails, search, read headers & bodies, send
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    # Google Drive: list and read user files
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
    # Google Calendar: list events and schedule
    "https://www.googleapis.com/auth/calendar",
    # Google Tasks: to-do items and notes
    "https://www.googleapis.com/auth/tasks",
]

SETUP_GUIDE_BURMESE = """⚠️ Google Services ချိတ်ဆက်ရန် `credentials.json` လိုအပ်ပါသည်-

၁။ Google Cloud Console (https://console.cloud.google.com/) သို့ သွားပါ။
၂။ Project အသစ်တစ်ခု ပြုလုပ်ပါ (ဥပမာ- Jarvis Assistant)။
၃။ 'APIs & Services' > 'Library' တွင် အောက်ပါ API များကို Enable လုပ်ပါ:
    • Gmail API
    • Google Drive API
    • Google Calendar API
    • Google Tasks API
၄။ 'OAuth consent screen' တွင် User Type: External ရွေးပြီး App Name ပေးပါ (Test users ထဲတွင် မိမိ Gmail ထည့်ပါ)။
၅။ 'Credentials' > 'Create Credentials' > 'OAuth client ID' ကို နှိပ်ပါ (Application Type: 'Desktop app' ရွေးပါ)။
၆။ ထွက်လာသော JSON ဖိုင်ကို ဒေါင်းလုဒ်ရယူပြီး `config/credentials.json` အဖြစ် ထည့်သွင်းပေးပါ။

ထို့နောက် JARVIS အား ပြန်လည်မေးမြန်းပါက Browser ပွင့်လာပြီး မိမိ Google အကောင့်ဖြင့် တစ်ကြိမ်သာ Login ပေးရပါမည်။"""


def get_credentials_path() -> Optional[Path]:
    """Find existing client credentials JSON file in config/."""
    for p in _CREDENTIAL_CANDIDATES:
        if p.exists() and p.is_file():
            return p
    return None


def get_credentials(interactive: bool = True) -> Tuple[Optional[Credentials], str]:
    """Retrieve or refresh valid Google OAuth2 credentials.

    Returns (credentials, error_or_guide_message).
    """
    creds: Optional[Credentials] = None

    # 1. Load existing token if present
    if _TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), SCOPES)
        except Exception as e:
            logger.warning("Failed to load token file: %s", e)
            creds = None

    # 2. Check validity and refresh if expired
    if creds and creds.valid:
        return creds, ""

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            return creds, ""
        except Exception as e:
            logger.warning("Token refresh failed: %s; re-authenticating...", e)
            creds = None

    # 3. New authorization flow
    cred_file = get_credentials_path()
    if not cred_file:
        return None, SETUP_GUIDE_BURMESE

    if not interactive:
        return None, "Google authorization required. Please run interactive setup."

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(cred_file), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        return creds, ""
    except Exception as e:
        logger.error("OAuth flow failed: %s", e)
        return None, f"⚠️ Google Authentication မအောင်မြင်ပါ: {e}"


def get_service(api_name: str, api_version: str) -> Tuple[Optional[Any], str]:
    """Get a Google API client service instance."""
    creds, err = get_credentials()
    if not creds:
        return None, err
    try:
        service = build(api_name, api_version, credentials=creds, cache_discovery=False)
        return service, ""
    except Exception as e:
        return None, f"⚠️ Google {api_name} Service ချိတ်ဆက်မှု မအောင်မြင်ပါ: {e}"


def get_gmail_service() -> Tuple[Optional[Any], str]:
    return get_service("gmail", "v1")


def get_drive_service() -> Tuple[Optional[Any], str]:
    return get_service("drive", "v3")


def get_calendar_service() -> Tuple[Optional[Any], str]:
    return get_service("calendar", "v3")


def get_tasks_service() -> Tuple[Optional[Any], str]:
    return get_service("tasks", "v1")

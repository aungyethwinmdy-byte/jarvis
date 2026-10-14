"""Quick diagnostic and authentication helper for JARVIS Google Services.

Run:
    python check_google.py
"""
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding="utf-8")

from core.google_auth import (
    get_calendar_service,
    get_credentials_path,
    get_drive_service,
    get_gmail_service,
    get_tasks_service,
)


def main():
    print("=" * 60)
    print("JARVIS Google Services Diagnostic & Auth Check")
    print("=" * 60)

    cred_path = get_credentials_path()
    if cred_path:
        print(f"✅ Credentials found at: {cred_path}")
    else:
        print("❌ No credentials file found in config/ (expected credentials.json)")
        print("   Please follow the setup guide to download credentials.json from Google Cloud Console.")
        return 1

    print("\nAttempting Google OAuth authorization...")
    gmail_srv, g_err = get_gmail_service()
    if not gmail_srv:
        print(f"❌ Gmail auth error:\n{g_err}")
        return 1

    print("✅ Gmail service connected successfully!")

    # Test Gmail
    try:
        profile = gmail_srv.users().getProfile(userId="me").execute()
        print(f"   Email Address: {profile.get('emailAddress')}")
        print(f"   Total Messages: {profile.get('messagesTotal')}")
    except Exception as e:
        print(f"⚠️ Could not fetch Gmail profile: {e}")

    # Test Drive
    drive_srv, d_err = get_drive_service()
    if drive_srv:
        print("✅ Google Drive connected!")
    else:
        print(f"⚠️ Google Drive error: {d_err}")

    # Test Calendar
    cal_srv, c_err = get_calendar_service()
    if cal_srv:
        print("✅ Google Calendar connected!")
    else:
        print(f"⚠️ Google Calendar error: {c_err}")

    # Test Tasks
    tasks_srv, t_err = get_tasks_service()
    if tasks_srv:
        print("✅ Google Tasks connected!")
    else:
        print(f"⚠️ Google Tasks error: {t_err}")

    print("\n" + "=" * 60)
    print("🎉 All configured Google Services are ready to use in JARVIS!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

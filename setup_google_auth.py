"""Google OAuth Local Server Setup Script.

Starts the local OAuth server on port 8088, prints the login URL with flush,
uses Windows 'start' to open the browser, and saves the token to config/google_token.json.
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

# Ensure UTF-8 output and unbuffered
sys.stdout.reconfigure(encoding="utf-8")

from google_auth_oauthlib.flow import InstalledAppFlow
from core.google_auth import get_credentials_path, SCOPES, _TOKEN_FILE

def main():
    cred_file = get_credentials_path()
    if not cred_file:
        print("ERROR: config/credentials.json not found!", flush=True)
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(cred_file), SCOPES)
    flow.redirect_uri = "http://localhost:8088/"
    
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    
    print("\n" + "=" * 60, flush=True)
    print("GOOGLE_AUTH_URL_START", flush=True)
    print(auth_url, flush=True)
    print("GOOGLE_AUTH_URL_END", flush=True)
    print("=" * 60 + "\n", flush=True)
    
    # Try launching Windows browser via shell start
    try:
        subprocess.Popen(["cmd.exe", "/c", "start", "", auth_url], shell=False)
    except Exception as e:
        print(f"Could not launch browser automatically: {e}", flush=True)

    print("Waiting for authentication on http://localhost:8088/ ...", flush=True)
    creds = flow.run_local_server(
        host="localhost",
        port=8088,
        open_browser=False,
    )
    
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
        
    print(f"\nSUCCESS: Token saved to {_TOKEN_FILE}!", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())

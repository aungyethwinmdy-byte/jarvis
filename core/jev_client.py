"""TypeSafe Jev client for Mark-LIV.

Connects to TypeSafe's Jev (System One Decision Model) via OpenRouter or TypeSafe API.
Follows the typesafe-ai skill patterns:
  - Judgments from Jev, decisions in code.
  - Primitives: choice, noul (yes/no probability), score, and intent routing.
  - Keeps payload and max_tokens bounded to prevent quota spikes.
  - Never raises out: returns graceful fallbacks on error.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional


def _get_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_api_key() -> str:
    """Retrieve OpenRouter or TypeSafe API key from config or environment."""
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key.strip()

    cfg_path = _get_base_dir() / "config" / "api_keys.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return (data.get("openrouter_api_key") or data.get("typesafe_api_key") or "").strip()
        except Exception:
            return ""
    return ""


def is_available() -> tuple[bool, str]:
    """Check if API key is configured."""
    key = _load_api_key()
    if not key:
        return False, "API key missing in config/api_keys.json"
    return True, "ok"


def call_jev(prompt: str, max_tokens: int = 30, temperature: float = 0.0, timeout: float = 8.0) -> dict[str, Any]:
    """Execute a request against TypeSafe Jev Router on OpenRouter.

    Returns dict with keys: 'ok', 'content', 'model', 'error'.
    """
    key = _load_api_key()
    if not key:
        return {"ok": False, "content": "", "model": "", "error": "No API key configured."}

    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": "typesafe/jev-router",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max(10, min(max_tokens, 150)),
        "temperature": temperature,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Jarvis-Mark-LIV",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "").strip()
            model = data.get("model", "typesafe/jev-router")
            return {"ok": True, "content": content, "model": model, "error": ""}
    except urllib.error.HTTPError as exc:
        err_msg = f"HTTP {exc.code}"
        try:
            body = exc.read().decode("utf-8")
            err_json = json.loads(body)
            err_msg += f": {err_json.get('error', {}).get('message', '')}"
        except Exception:
            pass
        return {"ok": False, "content": "", "model": "", "error": err_msg}
    except Exception as exc:
        return {"ok": False, "content": "", "model": "", "error": str(exc)}


def route_intent(user_text: str, candidate_actions: dict[str, str]) -> tuple[str, str]:
    """Route a user request to one of candidate action names using Jev.

    candidate_actions: dict of action_name -> description.
    Returns (action_name, debug_info).
    """
    if not candidate_actions:
        return "", "No candidate actions provided"

    options_desc = "\n".join(f"- {name}: {desc}" for name, desc in candidate_actions.items())
    prompt = (
        "You are Jev, a System One Decision Engine for JARVIS assistant.\n"
        f"Available actions:\n{options_desc}\n\n"
        f"User request: '{user_text}'\n"
        f"Select the single best action name from [{', '.join(candidate_actions.keys())}].\n"
        "Reply with ONLY the action name, nothing else."
    )

    res = call_jev(prompt, max_tokens=15)
    if not res["ok"]:
        return "", res["error"]

    chosen = res["content"].strip().lower()
    for name in candidate_actions.keys():
        if name.lower() in chosen:
            return name, f"Routed by {res['model']}"

    return chosen, f"Raw response from {res['model']}"


def decide_noul(state: str, statement: str) -> tuple[Optional[bool], float, str]:
    """Determine whether a statement is true about state (Noul primitive).

    Returns (decision_bool, confidence_float, debug_info).
    Thresholds: > 0.7 = True, < 0.3 = False, 0.3-0.7 = None (unsettled).
    """
    import re

    prompt = (
        f"Context: {state}\n"
        f"Statement: {statement}\n"
        "Is the statement true about the context? "
        "Answer with ONLY a float number from 0.0 to 1.0 (e.g. 0.95 or 0.05), nothing else."
    )

    res = call_jev(prompt, max_tokens=15)
    if not res["ok"]:
        return None, 0.0, res["error"]

    raw = res["content"].strip()
    m = re.search(r"\b(0(?:\.\d+)?|1(?:\.0+)?)\b", raw)
    if m:
        try:
            val = float(m.group(1))
            decision = True if val >= 0.7 else (False if val <= 0.3 else None)
            return decision, val, f"Evaluated by {res['model']}"
        except ValueError:
            pass

    low = raw.lower()
    if "yes" in low or "true" in low:
        return True, 0.95, f"Evaluated by {res['model']}"
    if "no" in low or "false" in low:
        return False, 0.05, f"Evaluated by {res['model']}"
    return None, 0.5, f"Evaluated by {res['model']}: '{raw}'"

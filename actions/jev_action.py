"""Action: jev_action — TypeSafe Jev System One Decision Engine for JARVIS.

Allows JARVIS to rapidly evaluate structured decisions, yes/no probabilities (Noul),
or intent classifications using TypeSafe's Jev model.
"""
from __future__ import annotations

from typing import Any

from core import jev_client


def jev_action(parameters: dict[str, Any], player=None, session_memory=None) -> str:
    """Evaluate decisions using TypeSafe Jev."""
    ok, reason = jev_client.is_available()
    if not ok:
        return f"TypeSafe Jev API Key မရှိသေးပါ ({reason})။ config/api_keys.json တွင် စစ်ဆေးပေးပါ။"

    action_type = str(parameters.get("action_type") or "noul").strip().lower()
    state = str(parameters.get("state") or "").strip()
    query = str(parameters.get("query") or "").strip()

    if not state and not query:
        return "ဆုံးဖြတ်ချက်ချမှတ်ရန် အချက်အလက် (state သို့မဟုတ် query) ထည့်သွင်းပေးရန် လိုအပ်ပါသည်။"

    if action_type == "noul":
        # Yes / No probability evaluation
        decision, conf, debug = jev_client.decide_noul(state or query, query or state)
        if decision is True:
            res_text = f"မှန်ကန်ပါသည် (True) — ရေရာမှုနှုန်း {conf*100:.1f}%"
        elif decision is False:
            res_text = f"မှားယွင်းပါသည် (False) — ရေရာမှုနှုန်း {(1.0-conf)*100:.1f}%"
        else:
            res_text = f"မသေချာပါ (Unsettled) — ရေရာမှုနှုန်း {conf*100:.1f}%"
        return f"Jev ဆုံးဖြတ်ချက်: {res_text} ({debug})"

    elif action_type == "choice":
        options_raw = parameters.get("options") or []
        if isinstance(options_raw, str):
            options = [o.strip() for o in options_raw.split(",") if o.strip()]
        else:
            options = [str(o).strip() for o in options_raw if str(o).strip()]

        if not options:
            return "Choice ရွေးချယ်ရန်အတွက် options စာရင်း ထည့်သွင်းပေးရန် လိုအပ်ပါသည်။"

        candidates = {opt: opt for opt in options}
        chosen, debug = jev_client.route_intent(state or query, candidates)
        return f"Jev ရွေးချယ်မှု: '{chosen}' ({debug})"

    else:
        # General query / evaluation
        prompt = f"Context: {state}\nQuestion: {query}\nProvide a concise System One decision."
        res = jev_client.call_jev(prompt, max_tokens=30)
        if not res["ok"]:
            return f"Jev ချိတ်ဆက်မှု အဆင်မပြေပါ: {res['error']}"
        return f"Jev ဆုံးဖြတ်ချက်: {res['content']} ({res['model']})"


TOOL = {
    "name": "jev_action",
    "description": (
        "Uses TypeSafe Jev (System One decision model) to evaluate structured decisions, "
        "judge if a statement is true/false with calibrated confidence (action_type='noul'), "
        "or select the best option from a list (action_type='choice'). Use this when the user "
        "explicitly asks to run Jev or wants an ultra-fast calibrated probability judgment."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action_type": {
                "type": "STRING",
                "description": "Decision primitive to run: 'noul' (yes/no probability), 'choice' (select from options), or 'query'.",
            },
            "state": {
                "type": "STRING",
                "description": "The context text or application state to evaluate.",
            },
            "query": {
                "type": "STRING",
                "description": "The statement to test or question to judge against the state.",
            },
            "options": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "List of string options when action_type is 'choice'.",
            },
        },
        "required": ["action_type"],
    },
    "handler": jev_action,
}

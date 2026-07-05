import base64
import json
import os
import sys

import requests
import functions_framework

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _format_message(payload: dict) -> str:
    incident = payload.get("incident", {})
    condition_name = incident.get("condition_name", "unknown")
    state = incident.get("state", "unknown")
    summary = incident.get("summary", "")
    url = incident.get("url", "")
    icon = "\u2705" if state == "closed" else "\U0001f6a8"
    return (
        f"{icon} SignFinder Alert\n"
        f"Condition: {condition_name}\n"
        f"State: {state}\n"
        f"Summary: {summary}\n"
        f"Details: {url}"
    )


@functions_framework.cloud_event
def alert_to_telegram(cloud_event):
    bot_token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("CHAT_ID")

    if not bot_token or not chat_id:
        print("ERROR: BOT_TOKEN or CHAT_ID not configured", file=sys.stderr)
        return

    try:
        message_data = cloud_event.data.get("message", {})
        b64 = message_data.get("data", "")
        raw = base64.b64decode(b64).decode("utf-8-sig").strip()
        payload = json.loads(raw)
    except Exception as exc:
        print(f"ERROR decode/parse failed: {exc!r}", file=sys.stderr)
        return

    text = _format_message(payload)

    try:
        response = requests.post(
            TELEGRAM_API_URL.format(token=bot_token),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if response.status_code != 200:
            print(f"ERROR Telegram API {response.status_code}: {response.text}", file=sys.stderr)
    except Exception as exc:
        print(f"ERROR Telegram call failed: {exc!r}", file=sys.stderr)

"""
Send a test Pub/Sub message to signfinder-alerts topic.
Bypasses PowerShell argument escaping entirely.
Run: python monitoring/send_test_alert.py
Requires: gcloud auth application-default login
"""
import base64
import json

from google.auth import default
from google.auth.transport.requests import Request
import requests

PROJECT = "signfinder-prod"
TOPIC = "signfinder-alerts"

payload = {
    "incident": {
        "condition_name": "Test Alert",
        "state": "open",
        "summary": "Pipeline test via Python script",
        "url": "https://console.cloud.google.com",
    }
}

data_b64 = base64.b64encode(json.dumps(payload).encode()).decode()

creds, _ = default()
creds.refresh(Request())

url = f"https://pubsub.googleapis.com/v1/projects/{PROJECT}/topics/{TOPIC}:publish"
resp = requests.post(
    url,
    headers={"Authorization": f"Bearer {creds.token}"},
    json={"messages": [{"data": data_b64}]},
)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text}")

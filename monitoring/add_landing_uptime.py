"""
Добавляет uptime check для лендинга signfinder.app и alert policy к нему.
Запуск: python monitoring\add_landing_uptime.py
"""
import json, subprocess, urllib.request, urllib.error, sys

PROJECT = "signfinder-prod"

def get_token():
    return subprocess.check_output(
        ["gcloud", "auth", "print-access-token"], shell=(sys.platform == "win32")
    ).decode().strip()

def api_call(method, path, body=None):
    token = get_token()
    url = f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        print(f"  ERROR {e.code}: {e.read().decode()}")
        return None

# 1. Uptime check для лендинга
print("[1/3] Uptime check for signfinder.app...")
result = api_call("POST", "uptimeCheckConfigs", {
    "displayName": "SignFinder Landing /",
    "httpCheck": {"path": "/", "port": 443, "useSsl": True, "validateSsl": True},
    "monitoredResource": {
        "type": "uptime_url",
        "labels": {"host": "signfinder.app", "project_id": PROJECT}
    },
    "period": "60s",
    "timeout": "10s"
})
if not result:
    sys.exit(1)
print(f"  OK: {result.get('name')}")

# 2. Найти существующий notification channel
print("[2/3] Finding notification channel...")
channels = api_call("GET", "notificationChannels")
channel_list = (channels or {}).get("notificationChannels", [])
pubsub_channels = [c for c in channel_list if c.get("type") == "pubsub"]
if not pubsub_channels:
    print("  ERROR: no pubsub channel found. Run setup_monitoring.py first.")
    sys.exit(1)
channel_name = pubsub_channels[-1]["name"]
print(f"  OK: {channel_name}")

# 3. Alert policy для лендинга
print("[3/3] Alert policy for landing downtime...")
result = api_call("POST", "alertPolicies", {
    "displayName": "SignFinder — Landing page down",
    "combiner": "OR",
    "conditions": [{
        "displayName": "signfinder.app not responding",
        "conditionThreshold": {
            "filter": 'resource.type="uptime_url" AND resource.labels.host="signfinder.app" AND metric.type="monitoring.googleapis.com/uptime_check/check_passed"',
            "comparison": "COMPARISON_LT",
            "thresholdValue": 1,
            "duration": "60s",
            "aggregations": [{
                "alignmentPeriod": "60s",
                "perSeriesAligner": "ALIGN_NEXT_OLDER",
                "crossSeriesReducer": "REDUCE_COUNT_FALSE",
                "groupByFields": ["resource.label.host"]
            }]
        }
    }],
    "notificationChannels": [channel_name],
    "severity": "CRITICAL",
    "enabled": True
})
if result:
    print(f"  OK: {result.get('displayName')}")

print("\n✅ Landing uptime monitoring added.")

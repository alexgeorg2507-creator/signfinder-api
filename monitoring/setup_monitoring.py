"""
Создаёт полный мониторинг SignFinder в Cloud Monitoring:
  - Notification channel (Pub/Sub → alert-to-telegram)
  - Uptime check (/health)
  - 4 alert policies

Запуск: python3 monitoring/setup_monitoring.py
Требует: gcloud auth login (уже есть)
"""
import json
import subprocess
import urllib.request
import urllib.error
import sys

PROJECT = "signfinder-prod"
TOPIC = f"projects/{PROJECT}/topics/signfinder-alerts"
API_URL = "https://signfinder-api-cvuz6bbb7a-ew.a.run.app"


def get_token():
    return subprocess.check_output(
        ["gcloud", "auth", "print-access-token"], shell=(sys.platform == "win32")
    ).decode().strip()


def api_call(method, path, body=None):
    token = get_token()
    url = f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  ERROR {e.code}: {e.read().decode()}")
        return None


def logging_api_call(method, path, body=None):
    token = get_token()
    url = f"https://logging.googleapis.com/v2/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        if "already exists" in err or "ALREADY_EXISTS" in err:
            print("  already exists, skipping")
            return {"name": f"projects/{PROJECT}/metrics/firebase-auth-failures"}
        print(f"  ERROR {e.code}: {err}")
        return None


# ── 1. Notification Channel ───────────────────────────────────────────────────
print("\n[1/4] Creating notification channel...")
result = api_call("POST", "notificationChannels", {
    "displayName": "SignFinder Telegram via Pub/Sub",
    "type": "pubsub",
    "labels": {"topic": TOPIC},
    "enabled": True
})

if not result:
    print("  Failed. Check that Pub/Sub topic exists and monitoring SA has publisher role.")
    sys.exit(1)

channel_name = result["name"]
print(f"  OK: {channel_name}")


# ── 2. Uptime Check ───────────────────────────────────────────────────────────
print("\n[2/4] Creating uptime check...")
hostname = API_URL.replace("https://", "")
result = api_call("POST", "uptimeCheckConfigs", {
    "displayName": "SignFinder API /health",
    "httpCheck": {
        "path": "/health",
        "port": 443,
        "useSsl": True,
        "validateSsl": True
    },
    "monitoredResource": {
        "type": "uptime_url",
        "labels": {"host": hostname, "project_id": PROJECT}
    },
    "period": "60s",
    "timeout": "10s"
})

if result:
    print(f"  OK: {result.get('name')}")
else:
    print("  Failed — continuing without uptime check")


# ── 3. Log-based metric for Firebase Auth failures ────────────────────────────
print("\n[3/4] Creating log-based metric for Firebase Auth failures...")
result = logging_api_call("POST", f"projects/{PROJECT}/metrics", {
    "name": "firebase-auth-failures",
    "description": "Firebase Auth failed login attempts",
    "filter": 'protoPayload.serviceName="identitytoolkit.googleapis.com" severity>=WARNING',
    "metricDescriptor": {"metricKind": "DELTA", "valueType": "INT64"}
})
if result:
    print(f"  OK: {result.get('name')}")


# ── 4. Alert Policies ─────────────────────────────────────────────────────────
print("\n[4/4] Creating alert policies...")

policies = [
    {
        "displayName": "SignFinder — API down (uptime)",
        "combiner": "OR",
        "conditions": [{
            "displayName": "Uptime check failed",
            "conditionThreshold": {
                "filter": 'resource.type="uptime_url" AND metric.type="monitoring.googleapis.com/uptime_check/check_passed"',
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
    },
    {
        "displayName": "SignFinder — Cloud Run high error rate",
        "combiner": "OR",
        "conditions": [{
            "displayName": "5xx rate > 5 req/min",
            "conditionThreshold": {
                "filter": 'resource.type="cloud_run_revision" AND resource.labels.service_name="signfinder-api" AND metric.type="run.googleapis.com/request_count" AND metric.labels.response_code_class="5xx"',
                "comparison": "COMPARISON_GT",
                "thresholdValue": 5,
                "duration": "300s",
                "aggregations": [{
                    "alignmentPeriod": "60s",
                    "perSeriesAligner": "ALIGN_RATE"
                }]
            }
        }],
        "notificationChannels": [channel_name],
        "severity": "ERROR",
        "enabled": True
    },
    {
        "displayName": "SignFinder — Cloud SQL disk > 80%",
        "combiner": "OR",
        "conditions": [{
            "displayName": "Disk utilization > 80%",
            "conditionThreshold": {
                "filter": 'resource.type="cloudsql_database" AND metric.type="cloudsql.googleapis.com/database/disk/utilization"',
                "comparison": "COMPARISON_GT",
                "thresholdValue": 0.8,
                "duration": "300s",
                "aggregations": [{
                    "alignmentPeriod": "300s",
                    "perSeriesAligner": "ALIGN_MEAN"
                }]
            }
        }],
        "notificationChannels": [channel_name],
        "severity": "WARNING",
        "enabled": True
    },
    {
        "displayName": "SignFinder — Firebase Auth anomaly",
        "combiner": "OR",
        "conditions": [{
            "displayName": "Failed logins > 50 per 10min",
            "conditionThreshold": {
                "filter": 'resource.type="global" AND metric.type="logging.googleapis.com/user/firebase-auth-failures"',
                "comparison": "COMPARISON_GT",
                "thresholdValue": 50,
                "duration": "600s",
                "aggregations": [{
                    "alignmentPeriod": "600s",
                    "perSeriesAligner": "ALIGN_SUM"
                }]
            }
        }],
        "notificationChannels": [channel_name],
        "severity": "WARNING",
        "enabled": True
    }
]

for policy in policies:
    result = api_call("POST", "alertPolicies", policy)
    if result:
        print(f"  OK: {result.get('displayName')}")
    else:
        print(f"  FAILED: {policy['displayName']}")


# ── Done ──────────────────────────────────────────────────────────────────────
print("\n✅ Done. Run to test:")
print(f"   python3 monitoring/send_test_alert.py")
print(f"\nCheck in GCP Console:")
print(f"   https://console.cloud.google.com/monitoring/alerting?project={PROJECT}")

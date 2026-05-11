"""Test multiple Sensor Tower endpoints for taxonomy/genre data."""
import os, json, requests
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.environ.get("SENSOR_TOWER_API_KEY", "")
BASE = "https://api.sensortower.com"

# App from the URL: unified_id=667ffe9c6e98fe0d9e01f33a, ios_id=6504332779
IOS_ID = "6504332779"
UNIFIED_ID = "667ffe9c6e98fe0d9e01f33a"

def get(url, params={}):
    params["auth_token"] = API_KEY
    r = requests.get(url, params=params, timeout=15)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        return r.json()
    print(f"  Body: {r.text[:300]}")
    return None

print("\n=== 1. v1/ios/apps (current) ===")
d = get(f"{BASE}/v1/ios/apps", {"app_ids[]": [IOS_ID], "country": "US"})
if d:
    apps = d.get("apps", d) if isinstance(d, dict) else d
    if isinstance(apps, list) and apps:
        app = apps[0]
        for f in ["categories","genre","genres","sub_genre","subgenre","taxonomy","game_taxonomy","genre_taxonomy","tags"]:
            if f in app: print(f"  {f}: {app[f]}")

print("\n=== 2. v1/unified/apps ===")
d = get(f"{BASE}/v1/unified/apps", {"app_ids[]": [UNIFIED_ID], "country": "US"})
if d:
    apps = d.get("apps", d) if isinstance(d, dict) else d
    if isinstance(apps, list) and apps:
        app = apps[0]
        print(f"  All keys: {sorted(app.keys())}")
        for f in ["categories","genre","genres","sub_genre","subgenre","taxonomy","game_taxonomy","genre_taxonomy","tags"]:
            if f in app: print(f"  {f}: {app[f]}")

print("\n=== 3. v1/ios/apps/app_details ===")
d = get(f"{BASE}/v1/ios/apps/app_details", {"app_id": IOS_ID, "country": "US"})
if d:
    if isinstance(d, dict):
        print(f"  Keys: {sorted(d.keys())}")
        for f in ["categories","genre","genres","sub_genre","taxonomy","game_taxonomy"]:
            if f in d: print(f"  {f}: {d[f]}")

print("\n=== 4. v2/unified/apps ===")
d = get(f"{BASE}/v2/unified/apps", {"app_ids[]": [UNIFIED_ID]})
if d:
    apps = d.get("apps", d) if isinstance(d, dict) else d
    if isinstance(apps, list) and apps:
        app = apps[0]
        print(f"  Keys: {sorted(app.keys())}")
        for f in ["categories","genre","genres","sub_genre","taxonomy","game_taxonomy","genre_taxonomy"]:
            if f in app: print(f"  {f}: {app[f]}")

print("\n=== 5. v1/unified/taxonomy ===")
d = get(f"{BASE}/v1/unified/taxonomy", {"app_ids[]": [UNIFIED_ID]})
if d: print(f"  Response: {str(d)[:500]}")

print("\n=== 6. v1/ios/apps/taxonomy ===")
d = get(f"{BASE}/v1/ios/apps/taxonomy", {"app_ids[]": [IOS_ID]})
if d: print(f"  Response: {str(d)[:500]}")

print("\nDone.")

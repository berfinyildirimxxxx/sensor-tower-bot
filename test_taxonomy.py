"""Quick test: does our API key return genre_taxonomy data?

Run once manually:
    python test_taxonomy.py

Prints the raw metadata for 2 known puzzle games so we can see
which fields Sensor Tower returns for our plan.
"""
import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.environ.get("SENSOR_TOWER_API_KEY", "")
BASE = "https://api.sensortower.com"

# Known puzzle game IDs to test with
TEST_IOS_IDS = ["6760331863", "6738703497"]  # Mahjong Jam, etc.

def fetch_metadata(app_ids, platform="ios"):
    url = f"{BASE}/v1/{platform}/apps"
    params = {
        "auth_token": API_KEY,
        "app_ids[]": app_ids,
        "country": "US",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

if not API_KEY:
    print("ERROR: SENSOR_TOWER_API_KEY not set")
    exit(1)

print("=== Fetching iOS metadata ===")
data = fetch_metadata(TEST_IOS_IDS, "ios")

# Print all field names and taxonomy-related fields
if isinstance(data, dict) and "apps" in data:
    apps = data["apps"]
elif isinstance(data, list):
    apps = data
else:
    apps = []
    print("Unexpected response shape:", type(data))
    print(json.dumps(data, indent=2)[:2000])

for app in apps[:2]:
    print(f"\n--- {app.get('name', app.get('app_id'))} ---")
    print("All fields:", sorted(app.keys()))
    # Print taxonomy-related fields if they exist
    for field in ["genre_taxonomy", "game_taxonomy", "taxonomy", "sub_genre",
                  "subgenre", "game_genre", "genres", "genre_tags",
                  "primary_genre", "category", "subcategories", "tags"]:
        if field in app:
            print(f"  {field}: {app[field]}")

print("\n=== Done ===")

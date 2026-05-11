"""Test: game_intel_data via session cookie."""
import os, requests, time, json
from dotenv import load_dotenv
load_dotenv()

SESSION = os.environ.get("SENSORTOWER_SESSION", "").strip()
if not SESSION:
    print("ERROR: SENSORTOWER_SESSION not set")
    exit(1)

headers = {
    "Cookie": f"sensor_tower_session={SESSION}; locale=en",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://app.sensortower.com/",
    "X-Requested-With": "XMLHttpRequest",
}

TEST_IDS = [
    "6760331863",  # Mahjong Jam
    "6757842718",  # Match-Blast
    "6504332779",  # Block
]

print(f"Testing {len(TEST_IDS)} apps...\n")
for app_id in TEST_IDS:
    url = f"https://app.sensortower.com/api/ios/apps/{app_id}?country=US"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        print(f"App {app_id}: status={r.status_code}")
        if r.status_code == 200:
            d = r.json()
            intel = d.get("game_intel_data")
            print(f"  game_intel_data type: {type(intel).__name__}, value: {intel}")
        else:
            print(f"  Body: {r.text[:200]}")
    except Exception as e:
        print(f"  Error: {e}")
    time.sleep(0.5)

print("\nDone.")

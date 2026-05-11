"""Test: game_intel_data via session cookie — just 5 apps, fast."""
import os, requests, time
from dotenv import load_dotenv
load_dotenv()

SESSION = os.environ.get("SENSORTOWER_SESSION", "").strip()
if not SESSION:
    print("ERROR: SENSORTOWER_SESSION not set")
    exit(1)

# Known iOS puzzle game IDs
TEST_IDS = [
    "6760331863",  # Mahjong Jam: Tile Match
    "6757842718",  # Match-Blast oyunu (sub_genre=Match-Blast bekliyoruz)
    "6738703497",  # başka bir oyun
    "6504332779",  # HAR'da Block sub_genre'ı olan oyun
    "6749264732",  # bir tane daha
]

headers = {
    "Cookie": f"sensor_tower_session={SESSION}",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}

print(f"Testing {len(TEST_IDS)} apps...\n")
for app_id in TEST_IDS:
    url = f"https://app.sensortower.com/api/ios/apps/{app_id}?country=US"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        print(f"App {app_id}: status={r.status_code}")
        if r.status_code == 200 and r.text.strip():
            d = r.json()
            intel = d.get("game_intel_data", {})
            if intel:
                print(f"  ✅ sub_genre: {intel.get('sub_genre', {}).get('name')}")
                print(f"     genre:     {intel.get('genre', {}).get('name')}")
                print(f"     category:  {intel.get('category', {}).get('name')}")
            else:
                print(f"  ⚠️  No game_intel_data. Keys: {list(d.keys())[:8]}")
        elif r.status_code == 401:
            print(f"  ❌ 401 Unauthorized — session expired!")
            break
        else:
            print(f"  ❌ {r.status_code}: {r.text[:100]}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    time.sleep(0.5)

print("\nDone.")

# Sensor Tower → Slack Puzzle Game Alert Bot

> Bu dosya hem kurulum rehberi hem de Codex'e adım adım verilecek prompt'ları içerir. Codex çalışırken bu dosyaya bakıp context alabilir.

---

## 0. Proje Özeti

Her gün Sensor Tower'dan son 24 saatte 500+ install alan yeni oyunları çek, Agave'nin iş alanına uygun olanları (puzzle / hybrid-casual / hidden object / sort / match / merge / tile / block / hex / jigsaw / word puzzle) filtrele, screenshot'larıyla birlikte özel bir Slack kanalına gönder. Aynı oyun iki kere gönderilmesin.

**Tech stack:**
- **Dil:** Python 3.11
- **Bot tipi:** Slack Incoming Webhook (basit, app/bot kurmaya gerek yok)
- **Veri kaynağı:** Sensor Tower REST API
- **Otomasyon:** GitHub Actions (her sabah cron ile çalışır)
- **Duplicate kontrolü:** Repo içinde `sent_games.json` dosyası (FID + package name)
- **Relevance scoring:** Şimdilik kategori + keyword bazlı (ilerde Claude API eklenecek şekilde modüler)

---

## 1. Sistem Mimarisi (Backend bilmeyen biri için)

```
┌─────────────────────┐
│  GitHub Actions     │  Her sabah 09:00 TR saatinde tetiklenir
│  (cron job)         │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  main.py            │  Python script çalışır
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Sensor Tower API    │  Son 24h, 500+ install, yeni oyunlar
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Filter & Score      │  Puzzle/hybrid-casual mu? Skor 0-100
│ (relevance.py)      │  >= 70 ise geç
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ sent_games.json     │  Daha önce gönderildi mi? Kontrol et
│ (duplicate check)   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Slack Webhook       │  Mesaj + screenshot'lar gönderilir
└─────────────────────┘
```

**Parçaları teker teker açıklayayım:**

1. **GitHub Actions:** GitHub'ın ücretsiz otomasyon servisi. "Her sabah 9'da şu kodu çalıştır" diyebiliyorsun. Kendi bilgisayarına ihtiyaç yok, GitHub kendi sunucusunda çalıştırıyor.

2. **Python script:** Asıl iş yapan kod. `main.py` her şeyi orkestre eder; `sensor_tower.py`, `relevance.py`, `slack.py` gibi dosyalar parçalı işleri yapar.

3. **Sensor Tower API:** API key ile bağlanıyoruz, JSON formatında oyun listesi alıyoruz.

4. **Slack Webhook:** Slack'te bir kanal için "Incoming Webhook" URL'i alıyorsun (5 dakikalık iş). O URL'e POST atınca o kanala mesaj düşüyor. Bot kurmaktan çok daha basit.

5. **sent_games.json:** Repo içinde duran küçük bir dosya. Her gönderilen oyunun FID'sini içine yazıyoruz. Ertesi gün aynı oyun gelirse atlıyoruz.

---

## 2. Kurulum Adımları (Sırasıyla yapılacak)

### Adım 0: Hesaplar ve erişimler
- [ ] GitHub hesabın var mı? Yoksa github.com'dan ücretsiz aç.
- [ ] Sensor Tower API key'in elinde mi? (Auth token)
- [ ] Slack'te yeni bir kanal aç (örn. `#new-puzzle-games`)
- [ ] O kanal için Incoming Webhook URL'i al (Bkz. Adım 4)

### Adım 1: GitHub repo oluştur
1. github.com → sağ üst "+" → "New repository"
2. İsim: `puzzle-game-alerts` (özel/private yap)
3. "Add a README" işaretle, "Create"

### Adım 2: Codex'e ilk prompt'u ver (Bölüm 3, Prompt 1)
Codex sana bir proje iskeleti çıkaracak. Bu dosyaları repoya ekleyeceksin.

### Adım 3: Sensor Tower API entegrasyonu (Prompt 2)

### Adım 4: Slack Webhook kurulumu
1. https://api.slack.com/apps → "Create New App" → "From scratch"
2. App name: `Puzzle Game Alerts`, workspace seç → Create
3. Sol menü "Incoming Webhooks" → toggle'ı aç
4. "Add New Webhook to Workspace" → kanalı seç → "Allow"
5. Çıkan URL'i kopyala (`https://hooks.slack.com/services/...`). Bu URL gizli kalmalı.

### Adım 5: Slack mesaj formatlama (Prompt 3)

### Adım 6: Filter + Relevance skoru (Prompt 4)

### Adım 7: Duplicate kontrolü (Prompt 5)

### Adım 8: GitHub Actions otomasyonu (Prompt 6)

### Adım 9: Secret'ları GitHub'a ekleme
GitHub repo → Settings → Secrets and variables → Actions → "New repository secret"
- `SENSOR_TOWER_API_KEY` = (Sensor Tower auth token)
- `SLACK_WEBHOOK_URL` = (Adım 4'te aldığın URL)

### Adım 10: Test ve devreye alma (Prompt 7)

---

## 3. Codex Prompt'ları

> **Berfin için kullanım notu:** Her prompt'u tek tek Codex'e ver. Codex çıktıyı verince bana geri at, ben kontrol edeyim. Sonra bir sonrakine geçeriz. Sırayla gitmek önemli — birini atlarsan sonraki çalışmaz.

---

### PROMPT 1 — Proje iskeleti

```
Create a Python 3.11 project structure for a Sensor Tower → Slack alert bot.

Requirements:
- Use a clean modular structure with separate files for each concern
- Use only standard libraries + `requests` for HTTP
- All configuration should come from environment variables (no hardcoded secrets)
- Add type hints to all functions
- Add docstrings explaining what each function does

Create these files:

1. `main.py` — orchestration entry point. Should call: fetch games → filter → dedupe → send to slack. For now leave each step as a TODO with a print statement.

2. `sensor_tower.py` — placeholder module with a function `fetch_new_games(min_installs: int = 500, lookback_hours: int = 24) -> list[dict]` that returns an empty list for now.

3. `relevance.py` — placeholder module with a function `score_game(game: dict) -> tuple[int, str, str]` that returns (score 0-100, reason, matched_mechanic). Return (0, "not implemented", "") for now.

4. `slack.py` — placeholder module with a function `send_game_alert(game: dict, score: int, reason: str, mechanic: str) -> bool`. Return True for now.

5. `dedupe.py` — placeholder module with two functions: `is_already_sent(game: dict) -> bool` (returns False) and `mark_as_sent(game: dict) -> None` (does nothing).

6. `config.py` — loads SENSOR_TOWER_API_KEY and SLACK_WEBHOOK_URL from os.environ. Raises a clear error if missing.

7. `requirements.txt` — list dependencies (just `requests` for now).

8. `README.md` — short setup instructions.

9. `.gitignore` — ignore `__pycache__`, `.env`, `venv/`, `*.pyc`.

10. `sent_games.json` — empty JSON object: `{}`

Do not implement business logic yet. Just create the skeleton with clear TODOs. Make sure `python main.py` runs without errors and prints the planned steps.
```

**Kontrol kriteri (bana geri attığında bakacaklarım):**
- 10 dosyanın hepsi var mı?
- `main.py` çalıştığında hata vermeden adımları print ediyor mu?
- Type hint'ler ve docstring'ler eklenmiş mi?
- Hardcoded API key var mı? (Olmamalı)

---

### PROMPT 2 — Sensor Tower API entegrasyonu

```
Implement the `sensor_tower.py` module to fetch new games from Sensor Tower's API.

Context:
- We want games that launched in the last 24 hours globally (all countries) on iOS and Android.
- Filter: games that received at least 500 installs in the last day.
- API authentication uses a bearer token from environment variable SENSOR_TOWER_API_KEY.

Reference Sensor Tower API documentation:
- New apps endpoint: /v1/{platform}/apps/new (returns recently launched apps)
- App details endpoint: /v1/{platform}/apps (returns metadata, screenshots, descriptions)
- Sales/installs endpoint: /v1/{platform}/sales_report_estimates_comparison (for install counts)

Implement:

```python
def fetch_new_games(min_installs: int = 500, lookback_hours: int = 24) -> list[dict]:
    """Fetch new games from Sensor Tower for both iOS and Android.

    Returns a list of dicts, each containing:
    - fid: str (Sensor Tower's unique ID)
    - app_id: str (package name on Android, app ID on iOS)
    - name: str
    - publisher: str
    - platform: str ("ios" or "android")
    - category: str (e.g. "Puzzle", "Casual")
    - subcategories: list[str]
    - description: str
    - keywords: list[str]
    - store_url: str
    - screenshots: list[str]  (URLs)
    - installs_last_day: int
    - country: str (top install country)
    - launch_date: str (ISO date)
    """
```

Implementation requirements:
- Make separate calls for iOS and Android, then merge results
- Handle API errors gracefully (log + return what you have, don't crash)
- Add a 1-second delay between paginated calls to avoid rate limits
- Use the `requests` library with timeout=30
- If the API returns nothing or fails, return []
- Add a docstring with the exact API endpoints used

Also update `main.py` to actually call `fetch_new_games()` and print the count + first 3 game names.

Important: If you're unsure about exact endpoint paths or parameters, add a clearly marked TODO and use placeholder paths. Do NOT invent fake API responses.
```

**Kontrol kriteri:**
- API key olmadan çalıştırınca anlamlı bir hata veriyor mu?
- API key ile çalıştırınca gerçek oyun listesi geliyor mu?
- Dönen dict'lerde yukarıda belirtilen tüm field'lar var mı?
- Hata halinde crash etmiyor mu?
- ⚠ Sensor Tower'ın gerçek endpoint'leri Codex'in tahmininden farklı olabilir. İlk çalıştırmada hata alırsak Sensor Tower API doc'unu açıp endpoint path'lerini düzelteceğiz.

---

### PROMPT 3 — Slack mesaj formatlama (screenshot'lar gömülü)

```
Implement the `slack.py` module to send a rich Slack message with embedded screenshots via Incoming Webhook.

Context:
- Slack webhook URL is in env var SLACK_WEBHOOK_URL.
- Screenshots must appear as actual images inside the message, NOT as text URLs.
- Use Slack Block Kit format with `image` blocks for screenshots.
- Show maximum 4 screenshots per message (Slack has block limits).

Implement:

```python
def send_game_alert(
    game: dict,
    score: int,
    reason: str,
    mechanic: str
) -> bool:
    """Post a formatted alert about one game to the configured Slack channel.

    Returns True on success, False on failure.
    """
```

The Slack message should use Block Kit with this structure:

1. Header block — game name (bold, big)
2. Section block with fields (2-column layout):
   - Developer/Publisher
   - Platform (iOS / Android with emoji)
   - Country / market
   - Installs (last 24h)
   - Relevance score (e.g. "85/100")
   - Matched mechanic (e.g. "Match-3", "Hidden Object")
3. Section block — "Why relevant" with the reason text
4. Action block — button "Open in Store" linking to store_url
5. Image blocks — up to 4 screenshots as inline images (NOT links)
6. Divider block at the end

Use this Slack Block Kit pattern for images:
{
    "type": "image",
    "image_url": "https://...",
    "alt_text": "Screenshot 1"
}

Implementation requirements:
- POST to SLACK_WEBHOOK_URL with Content-Type: application/json
- Timeout=15 seconds
- If webhook returns non-200, log the response body and return False
- Truncate description if longer than 200 chars
- Use platform emojis: 🍎 for iOS, 🤖 for Android
- Add a small "Sensor Tower data · {date}" context block at the bottom

Also add a function `send_test_message() -> bool` that posts "🧪 Bot test message — bağlantı çalışıyor" to verify webhook setup works.

Update `main.py` to call `send_test_message()` if env var BOT_TEST_MODE=1, otherwise proceed normally.
```

**Kontrol kriteri:**
- `BOT_TEST_MODE=1 python main.py` Slack'e test mesajı atıyor mu?
- Mesajda screenshot URL'i değil, gerçek görsel görünüyor mu?
- Tüm field'lar (developer, platform, install, vs) doğru yerde duruyor mu?
- "Open in Store" butonuna tıklayınca store açılıyor mu?

---

### PROMPT 4 — Relevance filtreleme + skorlama

```
Implement the `relevance.py` module to score games for puzzle/hybrid-casual relevance.

Context:
- Agave Games is a puzzle/hybrid-casual studio. Their benchmark titles include "What the Hex" and other puzzle/hidden-object games.
- We want to filter Sensor Tower's daily list down to games similar to these genres.
- For now, use a deterministic rule-based scorer. Later we'll add an LLM-based scorer; the function signature must stay the same so we can swap implementations.

Relevant genres/mechanics (with weights):
- match-3, match games → high
- merge puzzle, merge games → high
- hidden object → high
- jigsaw → high
- block puzzle, hex puzzle, tile puzzle → high
- sort puzzle (water sort, ball sort, etc.) → high
- word puzzle → medium-high
- casual puzzle, brain teaser → medium
- hybrid-casual (with puzzle elements) → medium
- generic "puzzle" category → medium (needs keyword confirmation)

NOT relevant (score these low):
- card games, slots, casino
- shooters, racing, action
- RPG, strategy, MMO
- sports games
- idle clickers (unless explicitly puzzle hybrid)
- music/rhythm games

Implement:

```python
RELEVANT_KEYWORDS = {
    "match": 25,
    "match-3": 30,
    "match 3": 30,
    "merge": 25,
    "hidden object": 35,
    "jigsaw": 30,
    "block puzzle": 25,
    "hex": 20,
    "tile": 20,
    "sort": 20,
    "water sort": 25,
    "ball sort": 25,
    "word puzzle": 20,
    "brain teaser": 15,
    "puzzle": 10,
    "casual": 5,
    "hybrid casual": 15,
    # ... extend
}

NEGATIVE_KEYWORDS = {
    "casino": -40,
    "slots": -40,
    "poker": -40,
    "shooter": -30,
    "racing": -30,
    "rpg": -25,
    "mmo": -30,
    "sports": -25,
    # ... extend
}

def score_game(game: dict) -> tuple[int, str, str]:
    """Score a game's relevance to Agave's puzzle/hybrid-casual focus.

    Returns:
        (score, reason, matched_mechanic)
        - score: 0-100
        - reason: short human-readable explanation of why this score
        - matched_mechanic: best-matching mechanic name (e.g. "Match-3"), or "" if none
    """
```

Scoring logic:
1. Start with score = 0
2. Check the `category` and `subcategories` fields — if "Puzzle" → +20
3. Tokenize and search the lowercase combined text of: name + description + keywords
4. For each RELEVANT_KEYWORDS match, add the weight (cap total keyword bonus at 60)
5. For each NEGATIVE_KEYWORDS match, subtract the weight
6. Clamp final score to 0-100
7. Determine `matched_mechanic` from highest-weighted matched keyword
8. `reason` should mention 1-3 things that drove the score (e.g. "Puzzle category + 'match-3' in name + hidden object keyword")

Add a function:

```python
def is_relevant(game: dict, threshold: int = 70) -> tuple[bool, int, str, str]:
    """Returns (is_relevant, score, reason, mechanic). Threshold default 70."""
```

Update `main.py` to:
- Fetch games
- Score each one
- Print a summary: "X games fetched, Y relevant (score >= 70)"
- Only continue with relevant ones

Write the keyword lists to be easily editable. Extend RELEVANT_KEYWORDS and NEGATIVE_KEYWORDS with at least 30 entries each based on common puzzle/hybrid-casual mobile game vocabulary.
```

**Kontrol kriteri:**
- Bilinen puzzle oyunları (Royal Match, Gardenscapes, Wordscapes vb. örnek input ver) yüksek skor alıyor mu?
- Casino/shooter oyunları düşük skor alıyor mu?
- "Reason" mantıklı bir cümle mi?
- Skor 70 threshold'u ile filtreleme doğru çalışıyor mu?

---

### PROMPT 5 — Duplicate kontrolü

```
Implement the `dedupe.py` module to prevent sending the same game twice.

Context:
- We track sent games in `sent_games.json` (committed to the repo so state persists across GitHub Actions runs).
- Identify duplicates by ANY of: FID, app_id (package name), or store_url match.
- Keep entries for 90 days, then prune to keep the file small.

JSON file structure:
```json
{
  "sent": {
    "fid_or_app_id": {
      "name": "Royal Match",
      "fid": "123456",
      "app_id": "com.dream.games.royalmatch",
      "store_url": "https://...",
      "sent_at": "2026-01-15T09:00:00Z"
    }
  }
}
```

Implement:

```python
def load_sent_games(path: str = "sent_games.json") -> dict:
    """Load the sent games registry. Return {} if file missing or empty."""

def save_sent_games(data: dict, path: str = "sent_games.json") -> None:
    """Save back to disk. Pretty-printed JSON."""

def is_already_sent(game: dict, registry: dict) -> bool:
    """Check if the game (by fid, app_id, or store_url) already exists in registry."""

def mark_as_sent(game: dict, registry: dict) -> None:
    """Add the game to the registry with current UTC timestamp."""

def prune_old_entries(registry: dict, days: int = 90) -> int:
    """Remove entries older than `days` days. Returns count of pruned entries."""
```

Update `main.py` to:
1. Load registry at start
2. Skip already-sent games (log: "Skipped X already-sent games")
3. After successful Slack send, mark game as sent
4. Prune entries older than 90 days
5. Save registry at the end

Important: Save the registry even if the script fails partway through (use try/finally). Otherwise we lose track.
```

**Kontrol kriteri:**
- İlk run'da `sent_games.json` doluyor mu?
- Aynı oyunla ikinci run'da Slack'e gitmiyor mu?
- 90 günden eski kayıtlar siliniyor mu?
- Script ortada crash olsa bile kayıt korunuyor mu?

---

### PROMPT 6 — GitHub Actions otomasyonu

```
Create a GitHub Actions workflow to run the bot daily.

Create `.github/workflows/daily-alert.yml` with:

- Schedule: every day at 06:00 UTC (= 09:00 Istanbul time)
- Manual trigger option (workflow_dispatch) for testing
- Python 3.11 setup
- Install dependencies from requirements.txt
- Run `python main.py`
- Pass secrets as env vars: SENSOR_TOWER_API_KEY, SLACK_WEBHOOK_URL
- After the run, commit any changes to `sent_games.json` back to the repo (so state persists)
- Use `actions/checkout@v4`, `actions/setup-python@v5`
- Set timezone properly so logs are readable

The commit step should:
- Use github-actions[bot] as author
- Only commit if there are actual changes
- Use a clear commit message like "chore: update sent games registry [skip ci]"
- Include `[skip ci]` in the commit message to prevent triggering another workflow

Also add a `BOT_TEST_MODE` workflow input (boolean, default false). When true, set BOT_TEST_MODE=1 env var so the script just sends a test message to Slack instead of running the full pipeline.

Add error handling:
- If the Python script fails, the workflow should fail visibly
- Add a step that, on failure, posts a simple "❌ Bot failed today, check logs" message to Slack via the same webhook

Output the workflow file content. Also write a short `OPERATIONS.md` explaining:
- How to manually trigger the workflow
- How to test in BOT_TEST_MODE
- How to view logs
- How to update secrets
```

**Kontrol kriteri:**
- Workflow dosyası `.github/workflows/daily-alert.yml` yolunda mı?
- Manuel tetikleme (workflow_dispatch) var mı?
- Secret'lar env var olarak geçiyor mu, kodda görünmüyor mu?
- `sent_games.json` her run sonunda commit'leniyor mu?
- Hata halinde Slack'e bildirim atıyor mu?

---

### PROMPT 7 — End-to-end test ve final polish

```
Now do an end-to-end review of the project and fix any integration issues.

Review checklist:
1. Read `main.py` and verify the full pipeline:
   fetch → score → filter (>= 70) → check duplicates → send to slack → mark as sent → save registry → prune
2. Make sure each step has clear log output (use the logging module, not print)
3. Ensure errors in one game don't crash the whole run (try/except around each game's processing)
4. Add a `--dry-run` flag that does everything except actually posting to Slack (just prints what would be sent)
5. Add a top-of-file summary log: "Run started at X, Y games fetched, Z relevant, W new (not duplicates), V sent successfully"
6. Add a basic local test mode: `python main.py --test` that uses a hardcoded sample game list from `tests/sample_games.json` (create this file with 3-5 example games covering relevant + irrelevant cases) and runs the pipeline against it without hitting Sensor Tower.

Also:
- Update `README.md` with: project overview, setup steps (env vars, secrets), how to run locally, how to run tests, how to read the daily report
- Add a `CHANGELOG.md` with entry "0.1.0 - Initial release"
- Make sure all Python files pass `python -m py_compile` (no syntax errors)

Finally, list any TODOs / known limitations as comments at the top of `main.py` so the user knows what to verify in production.
```

**Kontrol kriteri:**
- `python main.py --dry-run` Slack'e gerçek mesaj atmadan tüm pipeline'ı çalıştırıyor mu?
- `python main.py --test` örnek datayla çalışıyor mu?
- Log'lar anlaşılır mı?
- README başkasının okuyup kurabileceği netlikte mi?

---

## 4. Her Prompt Sonrası Kontrol Akışı

Codex bir prompt'a cevap verdiğinde şunu yap:

1. **Çıktı dosyalarını kopyala** ve bana at (sadece dosya adları + içerikleri yeter, çok uzun olursa parça parça).
2. **Ben kontrol kriterlerini gözden geçirip** sana "şu satır şüpheli", "şurası eksik" gibi geri dönüş yaparım.
3. **Düzeltme gerekiyorsa**, sana düzeltme prompt'u veririm — onu Codex'e atarsın.
4. **Onay verince** bir sonraki prompt'a geçeriz.

### Kontrol için bana göndermen gerekenler (her adımda):
- Oluşturulan/değiştirilen dosyaların tam içeriği
- Codex'in yaptığı varsayımlar / TODO bıraktığı yerler
- Eğer kod çalıştırdıysan, terminal çıktısı

### Sık karşılaşılacak problemler ve çözümler:

**Problem: Sensor Tower endpoint'leri yanlış**
- Çözüm: Sensor Tower API doc'unu açıp gerçek path'leri öğreneceğiz, Codex'e düzelttireceğiz.

**Problem: Slack webhook 400 dönüyor**
- Çözüm: Block Kit JSON'u Slack Block Kit Builder'da test et (https://app.slack.com/block-kit-builder), yapıyı düzelt.

**Problem: Skor sistemi bilinen puzzle oyunlarını kaçırıyor**
- Çözüm: `RELEVANT_KEYWORDS` listesine yeni keyword'ler ekle, ağırlıkları ayarla. Bu rule-based sistem demek bu — manuel tuning lazım.

**Problem: GitHub Actions çalışmıyor**
- Çözüm: Repo Settings → Actions → "Allow all actions" işaretli mi? Workflow dosyası `.github/workflows/` altında mı (büyük/küçük harf önemli)?

**Problem: `sent_games.json` her run'da çakışıyor**
- Çözüm: Workflow'da commit step'i doğru yapılandırılmamış. `git pull --rebase` ekle, sonra commit et.

---

## 5. İleride Eklenecekler (Phase 2 — Şirket onayı sonrası)

### Claude API ile akıllı relevance scoring
`relevance.py`'e ikinci bir fonksiyon ekleyeceğiz: `score_game_with_llm(game)`. Bu fonksiyon oyunun adı, açıklama, screenshot URL'leri ve keyword'lerini Claude'a gönderip "Bu oyun Agave'nin What the Hex / hidden object / puzzle benchmark'ına benziyor mu? 0-100 arası skor ver, gerekçeli." diye soracak. Maliyet günlük ~$0.50-2 civarı (50-200 oyun için).

Hazırlık: Bot'un mevcut hali bu eklemeye uygun yazıldı — sadece `score_game()` çağrısını `score_game_with_llm()` ile değiştireceğiz, geri kalan pipeline aynı kalacak.

### Diğer iyileştirmeler
- Haftalık özet raporu (Cuma günü, "bu hafta X relevant oyun bulundu")
- Belirli developer'ları (rakipler) flagleme
- Trend olan mekaniği vurgulama ("bu hafta 3 sort puzzle çıktı")

---

## 6. Hızlı Referans

| Şey | Yer / Değer |
|---|---|
| Cron zamanı | `0 6 * * *` UTC (09:00 İstanbul) |
| Min install eşiği | 500 / gün |
| Lookback | 24 saat |
| Relevance threshold | 70/100 |
| Duplicate kayıt süresi | 90 gün |
| Slack max screenshot | 4 |
| Python versiyonu | 3.11 |
| Secret #1 | `SENSOR_TOWER_API_KEY` |
| Secret #2 | `SLACK_WEBHOOK_URL` |

---

**Son not:** Bu dosyayı (`prompt.md`) repo'nun root'una koy. Codex'le çalışırken "bu dosyaya bak" diyerek context verebilirsin. Her prompt çıktısı sonrası bana geri at, beraber kontrol edelim.

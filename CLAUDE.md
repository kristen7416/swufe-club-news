# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Run crawl pipeline (in sequence)
python scripts/crawl_wechat.py
python scripts/extract_activity.py
python scripts/merge_data.py

# AI-powered enrichment (uses DeepSeek to patch missing fields)
$env:DEEPSEEK_API_KEY = "sk-..."; python scripts/extract_activity.py --enrich

# Search clubs by keyword
$env:WECHAT_COOKIE = "xxx"; python scripts/search_clubs.py

# Sync from Google Sheets (optional)
python scripts/sync_from_sheets.py

# Handle Windows Unicode (emoji) errors
python -X utf8 scripts/merge_data.py

# Run tests
python -m pytest scripts/tests/ -v

# Single test file
python -m pytest scripts/tests/test_wechat_to_md.py -v

# Cloudflare Worker 部署
cd workers
npm install -g wrangler          # 首次安装
wrangler secret put GITHUB_TOKEN # 设置 GitHub PAT
wrangler deploy                  # 部署 Worker
```

## Project Architecture

**SWUFE 社团活动资讯** — Aggregates club activity info from WeChat public accounts at 西南财经大学. Vanilla JS frontend + Python pipeline → GitHub Pages.

### Pipeline: WeChat → Static Data

```
clubs.json (96 clubs, 27 with wechat_name)
    │
    ▼
crawl_wechat.py  ──►  raw_articles.json
    │ WECHAT_COOKIE + __biz (fakeid) per club
    │ Uses mp.weixin.qq.com cgi-bin/appmsgpublish API
    │ Filters by max_age_days: 10 (configurable)
    │ Random delay 5-15s between club requests, 60s batch intervals
    │
    ▼
extract_activity.py  ──►  extracted_activities.json
    │ mode: "rule" (regex) or "ai" (DeepSeek API via DEEPSEEK_API_KEY)
    │ Has campus location KB for 柳林/光华校区
    │ Falls back to requests → markdownify for article body
    │
    ▼
merge_data.py  ──►  activities.json  (final output)
    │ Dedup by article_url
    │ Priority: manual > extracted > existing
    │ Recomputes status for all (time-based → heuristic → title keywords)
    │
    ▼
GitHub Actions (crawl-and-deploy.yml) → GitHub Pages
    │ Daily at UTC 18:00 (Beijing 02:00) + manual trigger
    │ Self-hosted Windows runner for crawl job
    │ Ubuntu runner for Pages deploy
```

### Key Source Files

| Path | Purpose |
|------|---------|
| `site/data/clubs.json` | Club registry: `id`, `name`, `wechat_name`, `biz` (base64 fakeid), `category`, `is_active`, `wechat_id` |
| `site/data/activities.json` | Auto-generated merged activity feed |
| `site/data/manual_activities.json` | Manual submissions from the publish form |
| `site/data/extracted_activities.json` | Pipeline intermediate: extracted activity data |
| `site/data/raw_articles.json` | Pipeline intermediate: raw WeChat API responses |
| `scripts/crawl_wechat.py` | WeChat API crawler. Uses session token from cookie, batches clubs, throttled |
| `scripts/extract_activity.py` | Activity extraction (regex or DeepSeek AI). Converts article HTML→Markdown. |
| `scripts/merge_data.py` | Merges extracted + manual activities, dedup, re-sorts, writes activities.json |
| `scripts/wechat_to_md.py` | WeChat article HTML→Markdown converter (Camoufox anti-detection browser) |
| `scripts/utils.py` | Shared: User-Agent rotation, retry logic, JSON load/save, timestamp parsing |
| `scripts/search_clubs.py` | WeChat search to discover clubs by keyword |
| `scripts/sync_from_sheets.py` | Google Sheets sync (optional, not actively used) |
| `api/submit-activity.py` | Vercel serverless: manual activity publish via GitHub Content API (legacy, replaced by CF Worker) |
| `workers/publish-worker.js` | Cloudflare Worker: 活动发布 API（公众号验证 + GitHub Content API 写入），中国可达 |
| `workers/wrangler.toml` | Cloudflare Worker 配置（含 GITHUB_REPO 变量） |
| `.github/workflows/crawl-and-deploy.yml` | CI/CD: crawl → merge → git commit → GitHub Pages deploy |

### Frontend (Vanilla JS, No Framework)

- **`site/index.html`** — Single-page app with: search bar, category nav (学术科技/文化艺术/体育竞技/志愿服务/创新创业/其他), status tabs (全部/即将开始/进行中/已结束), activity card grid, detail dialog, QR share card, publish form overlay
- **`site/js/app.js`** (~570 lines) — Data loading, filtering, search (300ms debounce), card rendering, detail dialog, QR code generation, card image save (html2canvas), top-section collapse on scroll. Pure ES5-compatible IIFE.
- **`site/js/publish.js`** (~158 lines) — Publish form: loads clubs with `wechat_name`, validates, POSTs to `/api/submit-activity`. URL validation requires `mp.weixin.qq.com`.
- **`site/js/qrcode.min.js`** — Third-party QR code generator
- **`site/js/html2canvas.min.js`** — Lazy-loaded for QR card image save
- **`site/css/style.css`** (~1240 lines) — All styles: CSS variables, dark mode (`@media prefers-color-scheme: dark`), responsive, card grid, collapse animation

### Data Model (activities.json)

```json
{
  "activities": [{
    "id": "club_001_20260526",
    "club_id": "club_001",
    "title": "活动标题",
    "description": "活动介绍",
    "category": "学术科技",
    "location": "经世楼B101",
    "start_time": "2026-05-26T14:00:00+08:00",
    "end_time": "2026-05-26T16:00:00+08:00",
    "article_url": "https://mp.weixin.qq.com/s/...",
    "cover_url": "",
    "publish_time": "2026-05-26T10:00:00+08:00",
    "contact": "QQ群 123456789",
    "source": "crawled",
    "status": "upcoming"
  }],
  "last_updated": "2026-05-26T10:00:00+08:00",
  "total_count": 49,
  "status_counts": { "upcoming": 10, "ongoing": 5, "ended": 34 }
}
```

### Activity Status Computation (three-tier, in `compute_status()`)

1. **Time-based**: Compare `start_time`/`end_time` against Beijing time
2. **Heuristic**: Published >7 days + start >1 day ago → `ended`. Published >30 days with no time → `ended`.
3. **Title keywords**: "圆满结束"/"回顾" → `ended`, "预告"/"报名" → `upcoming`

### WeChat Identity Verification (Publish Flow, `api/submit-activity.py`)

1. User submits article URL → API fetches HTML
2. Extracts nickname via regex patterns: `htmlDecode(` first, then plain string, then alternatives
3. Match logic: exact → prefix ("西财"/"SWUFE"/"西南财大"/"西南财经大学" + suffix) → substring
4. On match: appends to `manual_activities.json` → merges into `activities.json` via GitHub Content API

### Deployment

- **`vercel.json`** — Static site from `site/`, serverless function from `api/`, region `hkg1` (Hong Kong), data cache `s-maxage=300`
- **Current**: GitHub Pages is the active deployment (GitHub Actions workflow). Vercel deploy exists but is legacy.
- **GitHub Content API** — Used for write operations (publish flow). `GITHUB_TOKEN` stored as Vercel env var.

### Important Constraints

- **`.vercel.app` domains unreachable** from this environment — cannot test deployed API endpoints
- **Git push fails** — use GitHub Content API for writes
- **WeChat article pages** (`mp.weixin.qq.com`) ARE accessible for scraping
- **`__biz` only in article URL**, not in page HTML — needs an article URL to extract
- **Windows Unicode**: GBK encoding errors with emoji/Chinese → use `python -X utf8`
- **Self-hosted Windows runner** for CI/CD crawl job (needs `WECHAT_COOKIE` secret)
- **Network restrictions**: github.com is intermittent (China firewall), WeChat API accessible, mobile User-Agent recommended
- **Dependencies**: `requests`, `beautifulsoup4`, `lxml`, `markdownify`, `httpx`, `camoufox[geoip]`

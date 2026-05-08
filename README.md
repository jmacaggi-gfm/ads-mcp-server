# ads-mcp-server

Local MCP server exposing Google Ads + Meta Marketing performance data, campaign settings, and change history to Claude (Cowork) for live daily-dashboard workflows.

---

## What it does

Three tools registered with MCP:

| Tool | Purpose |
|---|---|
| `get_google_ads_report(date_range, breakdown)` | Performance + diagnostics + 56-day series + WoW + 8-week DoW comparisons + campaign settings + change history |
| `get_meta_ads_report(date_range, breakdown)` | Same shape as Google. Conversions filtered to `META_CONVERSION_EVENT_NAME` |
| `get_campaign_settings(platform)` | Settings + change history for `google` / `meta` / `both` |

Architecture: pull ad×day raw once per platform per hour, cache to parquet, derive every aggregation in pandas. No API call per breakdown.

---

## Prerequisites

- macOS / Linux
- Python 3.13 (via pyenv recommended)
- `uv` package manager: `brew install uv`
- Google Ads API access — see [Google Ads API getting started](https://developers.google.com/google-ads/api/docs/get-started/dev-token)
- Meta Marketing API access — see [Marketing API getting started](https://developers.facebook.com/docs/marketing-api/get-started)

### Credential setup links

| Credential | Where to get it |
|---|---|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Google Ads UI → Tools → API Center |
| `GOOGLE_ADS_CLIENT_ID` / `CLIENT_SECRET` | https://console.cloud.google.com → OAuth 2.0 client (Desktop app) |
| `GOOGLE_ADS_REFRESH_TOKEN` | Run `python -m google.ads.googleads.examples.authentication.generate_user_credentials` after installing `google-ads` |
| `GOOGLE_ADS_CUSTOMER_IDS` | Comma-separated, no dashes. Find in Google Ads UI top-right |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | MCC manager account ID, no dashes |
| `META_APP_ID` / `META_APP_SECRET` | https://developers.facebook.com → My Apps → Settings → Basic |
| `META_ACCESS_TOKEN` | https://business.facebook.com → Business Settings → System Users → Generate New Token (long-lived, with `ads_read`) |
| `META_AD_ACCOUNT_ID` | Meta Ads Manager → top-left account picker. Format: `act_XXXXXXXXX` |

---

## Install

```bash
cd ~/marketing-ds/ads-mcp-server
uv sync --extra dev
```

`uv` creates `.venv/` and installs all deps pinned in `pyproject.toml`.

---

## Configure credentials

Two options:

**Option A — point at existing `.env`** (recommended if you already have keys in `~/marketing-ds/decision_science/.env`):

```bash
export ADS_MCP_ENV_FILE=/Users/jmacaggi/marketing-ds/decision_science/.env
```

**Option B — local `.env`**:

```bash
cp .env.example .env
# fill in the blanks
```

Required keys are listed in `.env.example` with comments explaining each.

---

## Run

Locally for testing:

```bash
uv run ads-mcp-server
```

The server speaks MCP over stdio — Cowork (or any MCP client) spawns it on demand.

---

## Connect to Claude (Cowork)

Add this block to `~/.claude/claude_desktop_config.json` (create if missing):

```json
{
  "mcpServers": {
    "ads": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/jmacaggi/marketing-ds/ads-mcp-server",
        "run",
        "ads-mcp-server"
      ],
      "env": {
        "ADS_MCP_ENV_FILE": "/Users/jmacaggi/marketing-ds/decision_science/.env"
      }
    }
  }
}
```

Restart Claude/Cowork. Tools `get_google_ads_report`, `get_meta_ads_report`, `get_campaign_settings` should appear.

No background daemon required — Cowork starts/stops the process per session.

---

## Daily pre-warm (recommended for live dashboard)

Cache validity rule: a cache is fresh if it contains **yesterday's date**. Refreshes once per day. The first user query of the day triggers the refresh — and a 56-day pull on a large account can take 1-3 minutes.

To avoid that wait, schedule a pre-warm at 6am via macOS launchd:

```bash
# Install
cp /Users/jmacaggi/marketing-ds/ads-mcp-server/launchd/com.jmacaggi.adsmcp.prewarm.plist \
   ~/Library/LaunchAgents/

launchctl load ~/Library/LaunchAgents/com.jmacaggi.adsmcp.prewarm.plist

# Verify it's scheduled
launchctl list | grep adsmcp

# Trigger immediately (test)
launchctl start com.jmacaggi.adsmcp.prewarm

# Logs
tail -f ~/marketing-ds/ads-mcp-server/logs/prewarm.stdout.log
tail -f ~/marketing-ds/ads-mcp-server/logs/$(date +%Y-%m-%d).log
```

What it does each morning at 6am:
1. Pulls Google Ads perf 56d, settings, change_event 29d → cache
2. (Meta currently disabled — see "Meta status" below)
3. Writes refresh stamp `cache/google_lastrefresh.txt` = today

By the time you open Cowork, Google data is hot. Tool calls return in <1s.

To uninstall:
```bash
launchctl unload ~/Library/LaunchAgents/com.jmacaggi.adsmcp.prewarm.plist
rm ~/Library/LaunchAgents/com.jmacaggi.adsmcp.prewarm.plist
```

---

## Meta status (as of 2026-05-07)

Meta tools (`get_meta_ads_report`, `get_campaign_settings(platform="meta"|"both")`) are **structurally complete but not yet verified end-to-end**.

What works:
- Performance pull is chunked into 7-day windows (avoids the `Service temporarily unavailable / subcode 1504044` "result too large" error)
- Ad-level data is split: `level=campaign` for the 56-day series, `level=ad` for yesterday-only (avoids 5-minute pagination)
- AdSet pull is filtered to `effective_status IN [ACTIVE, PAUSED]` (avoids paginating thousands of archived ad sets)

What blocked us:
- After the first big perf chunked pull, the AdSet pull hit Meta's hourly rate limit (`code 17`, subcode 2446079: "User request limit reached"). Cooldown is typically 10-60 minutes.

To re-test tomorrow morning (after quota resets):
```bash
# Remove --skip-meta from the launchd plist to enable Meta in pre-warm
sed -i '' '/<string>--skip-meta<\/string>/d' \
   ~/Library/LaunchAgents/com.jmacaggi.adsmcp.prewarm.plist
launchctl unload ~/Library/LaunchAgents/com.jmacaggi.adsmcp.prewarm.plist
launchctl load ~/Library/LaunchAgents/com.jmacaggi.adsmcp.prewarm.plist

# Or run manually
ADS_MCP_ENV_FILE=/Users/jmacaggi/marketing-ds/decision_science/.env \
   uv run python scripts/prewarm.py
```

If Meta keeps rate-limiting, fallback options (not yet implemented):
- Async report runs (`async=True`) for the perf pull
- Tighter `effective_status` filter (`ACTIVE` only, drop paused)

If you prefer a long-running background process (optional, not required for Cowork): use `nohup uv run ads-mcp-server > /tmp/ads-mcp.log 2>&1 &` or a launchd plist.

---

## Optional: CSV override (skip the API)

Google Ads UI exports CSV reports without API quota limits. Drop a CSV into `cache/external/` to override the API pull:

```
cache/external/google_2026-05-07.csv
cache/external/meta_2026-05-07.csv
```

If a matching CSV exists AND is newer than the parquet cache, the server loads it instead of calling the API. The response sets `metadata.data_source = "csv_override"` so Cowork knows.

CSV column schema must match the parquet (see `src/ads_mcp_server/google_ads.py` and `meta_ads.py` for column names: `date, campaign_id, campaign_name, ad_id, ad_name, spend, impressions, clicks, conversions, ...`).

---

## Test

```bash
uv run pytest -v
```

All tests are mock-based — no network calls. Covers:
- `classify_campaign` Brand/Non-Brand/Other
- `diagnose` 5-state classifier
- 8-week same-DoW selector picks the right 8 dates
- WoW delta + zero-division
- `actions[]` filter for Meta
- Snapshot diff including null-old-value and pruning
- Missing creds returns clean error (no exception)

---

## Logs

Every API call and error is logged to `logs/YYYY-MM-DD.log` (one file per day).

---

## Troubleshooting

- **`google-ads` install fails**: ensure Python 3.13 (`uv python pin 3.13`) and `pip install grpcio` works on your system. On Apple Silicon: `arch -arm64 uv sync`.
- **Meta token expired**: regenerate the system user token in Business Settings; long-lived tokens last 60 days.
- **Tool not appearing in Cowork**: check `~/Library/Logs/Claude/mcp*.log` for spawn errors. Confirm `uv` is in `PATH` for the GUI process (you may need a full path: `which uv`).
- **Cache stale**: delete `cache/*.parquet` to force fresh pull.

---

## File map

```
src/ads_mcp_server/
  server.py        # MCP entry + tool handlers
  config.py        # env loading, validates creds
  google_ads.py    # 3 GAQL queries: perf, settings, change_event
  meta_ads.py      # Insights + AdSet pull
  snapshots.py     # Meta snapshot diff (Meta has no reliable change API)
  cache.py         # parquet + CSV override
  aggregate.py     # all pandas math
  classify.py      # Brand/NB/Other
  diagnose.py      # 5-state diagnosis
  date_ranges.py   # window resolution + 8wk DoW
  retry.py         # exponential backoff
  logging_setup.py # daily file logs
  schema.py        # response shape constants
```

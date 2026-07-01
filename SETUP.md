# Daily Viral NYC TikTok → Discord

A tiny, free automation that every morning at **7:00 AM Mountain** finds the most
viral NYC TikToks (ranked by views + likes + comments + shares) and posts the top 8
to your Discord channel.

## The tech stack (lean by design)

| Piece | What it does | Cost |
|-------|--------------|------|
| **Python script** (`viral_tiktok_nyc.py`) | Fetches, ranks, formats | free |
| **RapidAPI – TikTok Scraper** (`tiktok-scraper7`) | The TikTok data source | free tier, then ~$0.001–0.002/request |
| **Discord webhook** | Delivery | free |
| **GitHub Actions** | The scheduler (cron) — no server to run or pay for | free (2,000 min/mo) |

No server, no database, no always-on machine. GitHub runs it on a timer and shuts down.
Total moving parts: one script + one config file + two secrets.

> Why GitHub Actions and not run it inside Claude/Cowork? The delivery needs open
> internet access to reach TikTok's data API and Discord. GitHub Actions gives you
> that for free on a cron with zero infrastructure. It's the leanest option that
> actually runs unattended every day.

---

## Setup (about 15 minutes, one time)

### 1. Create the Discord webhook
1. In Discord, open the channel you want the digest in.
2. **Channel settings (⚙️) → Integrations → Webhooks → New Webhook**.
3. Name it (e.g. "NYC Viral TikTok"), then **Copy Webhook URL**. Save it.

### 2. Get a TikTok data API key (RapidAPI)
1. Sign up at https://rapidapi.com (free).
2. Subscribe to the **TikTok Scraper** API: https://rapidapi.com/tikwm-tikwm-default/api/tiktok-scraper7 (has a free tier).
3. On that API's page, copy your **`x-rapidapi-key`**.
   - Prefer a different provider? ScrapTik or LamaTok work too — just change
     `RAPIDAPI_HOST` and, if their field names differ, the `normalize_item()` function.

### 3. Put it on GitHub
1. Create a new **private** repo at https://github.com/new.
2. Upload these three files (keep the workflow in the right folder):
   ```
   viral_tiktok_nyc.py
   requirements.txt
   .github/workflows/daily-viral-tiktok.yml   <-- move daily-viral-tiktok.yml here
   ```
3. Add your secrets: repo **Settings → Secrets and variables → Actions → New repository secret**
   - `RAPIDAPI_KEY` = your RapidAPI key
   - `DISCORD_WEBHOOK_URL` = your Discord webhook URL

### 4. Test it now
- Repo → **Actions** tab → **Daily Viral NYC TikTok → Discord** → **Run workflow**.
- Manual runs skip the 7 AM guard, so you'll get a post within a minute if it's working.

That's it. It now runs automatically every morning at 7:00 AM Mountain, year-round.

---

## Tuning (edit the workflow's `env:` block, no code changes needed)

- `KEYWORDS` — search terms, e.g. `"nyc food,brooklyn,manhattan"`
- `HASHTAGS` — e.g. `"nyc,newyorkcity,fyp"`
- `TOP_N` — how many videos to post (max 10 per Discord message)
- `MAX_AGE_DAYS` — only count videos newer than this (default 7 = "viral *now*")
- Ranking weights live in `WEIGHTS` at the top of the script (views 40%, likes 25%,
  comments 20%, shares 15%). Each metric is min-max normalized across the batch so
  huge view counts don't drown out shares.

## Run locally to experiment
```bash
pip install -r requirements.txt
python viral_tiktok_nyc.py --demo      # offline sample data, prints the Discord payload
export RAPIDAPI_KEY=...  DISCORD_WEBHOOK_URL=...
python viral_tiktok_nyc.py --dry-run   # real fetch, prints instead of posting
python viral_tiktok_nyc.py             # real fetch + post
```

---

## No-code alternative (if you'd rather not touch GitHub)
Use **Apify's TikTok Hashtag Scraper** (https://apify.com/clockworks/tiktok-hashtag-scraper).
It has a built-in **scheduler** and a native **Discord/webhook integration**, so you can
run a daily hashtag scrape and pipe results out without writing code. Trade-off: less
control over the exact ranking formula and digest formatting, and it's ~$1.70 per 1,000
videos. The GitHub Actions route above is cheaper and fully customizable.

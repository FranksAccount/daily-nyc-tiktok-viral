#!/usr/bin/env python3
"""
Daily viral TikTok digest for NYC -> Discord.

Fetches recent TikTok videos for a set of NYC hashtags/keywords, ranks them by a
weighted virality score (views + likes + comments + shares), and posts the top N
to a Discord channel via webhook.

Data source: RapidAPI "TikTok Scraper" (tiktok-scraper7 / tikwm) by default.
Swap SEARCH_ENDPOINT / field names for any other provider (ScrapTik, LamaTok, etc.).

Env vars (set as GitHub Actions secrets):
  RAPIDAPI_KEY          - your RapidAPI key
  DISCORD_WEBHOOK_URL   - the Discord channel webhook URL

Optional env vars:
  RAPIDAPI_HOST         - default: tiktok-scraper7.p.rapidapi.com
  KEYWORDS              - comma list, default: "new york city,nyc,new york"
  HASHTAGS              - comma list, default: "nyc,newyorkcity,newyork,fyp nyc"
  MAX_AGE_DAYS          - only consider videos newer than this, default: 7
  TOP_N                 - how many to post, default: 8
  MOUNTAIN_HOUR_GUARD   - if set (e.g. "7"), script exits unless it's that hour
                          in America/Denver. Makes GitHub's UTC cron DST-safe.

Run modes:
  python viral_tiktok_nyc.py           # live: fetch + post to Discord
  python viral_tiktok_nyc.py --demo    # offline: use sample data, print payload
  python viral_tiktok_nyc.py --dry-run # live fetch, but print instead of posting
"""

import os
import sys
import json
import time
import datetime as dt
from zoneinfo import ZoneInfo

import requests

# ----------------------------- Config ---------------------------------------

RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST", "tiktok-scraper7.p.rapidapi.com")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

KEYWORDS = [k.strip() for k in os.getenv("KEYWORDS", "new york city,nyc,new york").split(",") if k.strip()]
HASHTAGS = [h.strip().lstrip("#") for h in os.getenv("HASHTAGS", "NYC,NewYorkCity,NYCTok,NYCFoodie,NYCLife,NYCEvents,NYCSubway,NYCStreetStyle,ExploreNYC,NYCApartment,NYCRestaurant,ConcreteJungle,NewYorkerTok,NYCContentCreator,VisitNYC").split(",") if h.strip()]

MAX_AGE_DAYS = int(os.getenv("MAX_AGE_DAYS", "1"))  # 1 = past 24 hours
TOP_N = int(os.getenv("TOP_N", "5"))
PER_QUERY = int(os.getenv("PER_QUERY", "30"))   # results to pull per keyword/hashtag

# Weighted virality score. Tune to taste (must not need to sum to 1).
WEIGHTS = {
    "views": 0.40,
    "likes": 0.25,
    "comments": 0.20,
    "shares": 0.15,
}

# tiktok-scraper7 endpoints
SEARCH_ENDPOINT = f"https://{RAPIDAPI_HOST}/feed/search"        # ?keywords=&count=
HASHTAG_ID_ENDPOINT = f"https://{RAPIDAPI_HOST}/challenge/info"  # ?challenge_name=
HASHTAG_POSTS_ENDPOINT = f"https://{RAPIDAPI_HOST}/challenge/posts"  # ?challenge_id=&count=

HEADERS = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": RAPIDAPI_HOST,
}

# --------------------------- Normalization ----------------------------------

def normalize_item(raw):
    """Map a provider's raw video object to a common schema.

    tiktok-scraper7 fields: play_count, digg_count, comment_count, share_count,
    title, author.unique_id, video_id, create_time (epoch seconds).
    Adjust here if you switch providers.
    """
    author = raw.get("author") or {}
    vid = str(raw.get("video_id") or raw.get("aweme_id") or raw.get("id") or "")
    uid = author.get("unique_id") or author.get("uniqueId") or ""
    return {
        "id": vid,
        "author": uid,
        "author_name": author.get("nickname") or uid,
        "caption": (raw.get("title") or raw.get("desc") or "").strip(),
        "views": int(raw.get("play_count") or raw.get("playCount") or 0),
        "likes": int(raw.get("digg_count") or raw.get("diggCount") or 0),
        "comments": int(raw.get("comment_count") or raw.get("commentCount") or 0),
        "shares": int(raw.get("share_count") or raw.get("shareCount") or 0),
        "create_time": int(raw.get("create_time") or raw.get("createTime") or 0),
        "cover": raw.get("cover") or raw.get("origin_cover") or "",
        "url": (f"https://www.tiktok.com/@{uid}/video/{vid}" if uid and vid
                else raw.get("play") or ""),
    }


# ------------------------------ Fetching ------------------------------------

def _get(url, params):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print(f"  ! request failed for {url} {params}: {e}", file=sys.stderr)
                return {}
            time.sleep(1.5 * (attempt + 1))
    return {}


def fetch_by_keyword(keyword):
    data = _get(SEARCH_ENDPOINT, {"keywords": keyword, "count": PER_QUERY, "region": "us"})
    items = (data.get("data") or {}).get("videos") or data.get("videos") or []
    return items


def fetch_by_hashtag(tag):
    info = _get(HASHTAG_ID_ENDPOINT, {"challenge_name": tag})
    challenge_id = ((info.get("data") or {}).get("challenge") or {}).get("id") \
        or (info.get("data") or {}).get("id")
    if not challenge_id:
        return []
    data = _get(HASHTAG_POSTS_ENDPOINT, {"challenge_id": challenge_id, "count": PER_QUERY})
    items = (data.get("data") or {}).get("videos") or data.get("videos") or []
    return items


def collect():
    seen = {}
    for kw in KEYWORDS:
        print(f"  keyword: {kw}")
        for it in fetch_by_keyword(kw):
            n = normalize_item(it)
            if n["id"]:
                seen[n["id"]] = n
    for tag in HASHTAGS:
        print(f"  #{tag}")
        for it in fetch_by_hashtag(tag):
            n = normalize_item(it)
            if n["id"]:
                seen[n["id"]] = n
    return list(seen.values())


# ------------------------------ Ranking -------------------------------------

def filter_recent(items):
    if MAX_AGE_DAYS <= 0:
        return items
    cutoff = time.time() - MAX_AGE_DAYS * 86400
    out = [i for i in items if i["create_time"] == 0 or i["create_time"] >= cutoff]
    return out


def score(items):
    """Min-max normalize each metric across the batch, then weighted sum."""
    if not items:
        return items
    maxes = {m: max((i[m] for i in items), default=0) or 1 for m in WEIGHTS}
    for i in items:
        i["virality"] = round(sum(
            WEIGHTS[m] * (i[m] / maxes[m]) for m in WEIGHTS
        ) * 100, 2)
    items.sort(key=lambda x: x["virality"], reverse=True)
    return items


# --------------------------- Discord delivery -------------------------------

def human(n):
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n/div:.1f}{unit}".replace(".0", "")
    return str(n)


def build_discord_payload(top):
    today = dt.datetime.now(ZoneInfo("America/Denver")).strftime("%A, %b %-d")
    embeds = []
    for rank, v in enumerate(top, 1):
        cap = v["caption"] or "(no caption)"
        if len(cap) > 180:
            cap = cap[:177] + "..."
        desc = (
            f"👁 **{human(v['views'])}** views  ❤️ {human(v['likes'])}  "
            f"💬 {human(v['comments'])}  🔁 {human(v['shares'])}\n"
            f"🔥 Virality score: **{v['virality']}**\n{cap}"
        )
        embed = {
            "title": f"#{rank}  @{v['author']}",
            "url": v["url"],
            "description": desc,
            "color": 0xEE1D52,  # TikTok red/pink
        }
        if v.get("cover"):
            embed["thumbnail"] = {"url": v["cover"]}
        embeds.append(embed)

    # Discord allows max 10 embeds per message
    return {
        "username": "NYC Viral TikTok",
        "content": f"🗽 **Top {len(top)} viral NYC TikToks — {today}**",
        "embeds": embeds[:10],
    }


def post_to_discord(payload):
    r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
    r.raise_for_status()
    print(f"  posted to Discord: HTTP {r.status_code}")


# ------------------------------- Main ---------------------------------------

DEMO_ITEMS = [
    {"video_id": "1", "author": {"unique_id": "nyceats", "nickname": "NYC Eats"},
     "title": "Best $1 pizza slice in Manhattan 🍕 #nyc #foodie",
     "play_count": 4200000, "digg_count": 610000, "comment_count": 8200, "share_count": 44000,
     "create_time": int(time.time()) - 2 * 86400, "cover": "https://example.com/a.jpg"},
    {"video_id": "2", "author": {"unique_id": "subwaydancer", "nickname": "Subway Dancer"},
     "title": "Rush hour breakdance on the L train #newyorkcity",
     "play_count": 9100000, "digg_count": 1200000, "comment_count": 15400, "share_count": 210000,
     "create_time": int(time.time()) - 1 * 86400, "cover": "https://example.com/b.jpg"},
    {"video_id": "3", "author": {"unique_id": "skylineviews", "nickname": "Skyline"},
     "title": "POV: sunset from the Brooklyn Bridge #nyc #fyp",
     "play_count": 2300000, "digg_count": 340000, "comment_count": 2100, "share_count": 29000,
     "create_time": int(time.time()) - 3 * 86400, "cover": "https://example.com/c.jpg"},
    {"video_id": "4", "author": {"unique_id": "bodegacat", "nickname": "Bodega Cat"},
     "title": "The most famous bodega cat in Queens 🐈 #newyork",
     "play_count": 1500000, "digg_count": 280000, "comment_count": 5600, "share_count": 12000,
     "create_time": int(time.time()) - 5 * 86400, "cover": "https://example.com/d.jpg"},
    {"video_id": "5", "author": {"unique_id": "timessq", "nickname": "Times Sq Live"},
     "title": "Naked Cowboy vs street preacher, who wins #nyc",
     "play_count": 700000, "digg_count": 90000, "comment_count": 900, "share_count": 4000,
     "create_time": int(time.time()) - 40 * 86400, "cover": "https://example.com/e.jpg"},
]


def main():
    demo = "--demo" in sys.argv
    dry = "--dry-run" in sys.argv or demo

    # DST-safe guard for GitHub's UTC-only cron.
    guard = os.getenv("MOUNTAIN_HOUR_GUARD")
    if guard and not demo:
        now_mt = dt.datetime.now(ZoneInfo("America/Denver"))
        if now_mt.hour != int(guard):
            print(f"Not {guard}:00 in Denver (it's {now_mt:%H:%M}). Skipping.")
            return

    if not demo:
        if not RAPIDAPI_KEY:
            sys.exit("ERROR: RAPIDAPI_KEY not set.")
        if not DISCORD_WEBHOOK_URL and not dry:
            sys.exit("ERROR: DISCORD_WEBHOOK_URL not set.")

    print("Collecting videos...")
    items = DEMO_ITEMS if demo else collect()
    items = [normalize_item(i) for i in items] if demo else items
    print(f"  {len(items)} unique videos collected")

    items = filter_recent(items)
    print(f"  {len(items)} within last {MAX_AGE_DAYS} days")

    items = score(items)
    top = items[:TOP_N]
    if not top:
        print("No videos to post.")
        return

    payload = build_discord_payload(top)

    if dry:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"\n[dry-run] Would post {len(top)} videos.")
        return

    post_to_discord(payload)
    print("Done.")


if __name__ == "__main__":
    main()

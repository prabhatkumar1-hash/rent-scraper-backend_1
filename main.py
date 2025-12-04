import os
import re
import asyncio
import logging
from typing import List, Dict, Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
from ddgs import DDGS
import httpx

# Basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rent-scraper").info

app = FastAPI(title="Rent Scraper (no-playwright)")

# Config
REQUEST_TIMEOUT = 15.0
MAX_CONCURRENT_FETCHES = 6
RETRY_COUNT = 2
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY")  # optional


# -----------------------------
# Utilities
# -----------------------------
def slugify(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s.strip("-").lower()


def extract_bhk_from_text(text: Optional[str]):
    if not text:
        return None
    m = re.search(r"(\d+)\s*[-]?\s*(?:BHK|bhk|Bhk)", text)
    if m:
        return f"{int(m.group(1))} BHK"
    return None


def parse_int_from_text(s: Optional[str]):
    if not s:
        return None
    # First try rupee patterns like "₹ 12,34,567" or "₹12,34,567"
    m = re.findall(r"₹\s*([0-9,]+)", s)
    if m:
        nums = [int(x.replace(",", "")) for x in m]
        return max(nums)
    # Otherwise look for 4-7 digit numbers (likely rent)
    m2 = re.findall(r"\b([0-9]{4,7})\b", s)
    if m2:
        nums = [int(x) for x in m2]
        return max(nums)
    return None


def extract_rent_from_url(url: str):
    # URL style used earlier: for-rs-<amount>
    m = re.search(r"for-rs-([0-9,]+)", url.replace(",", ""))
    if m:
        try:
            return int(m.group(1))
        except:
            return None
    return None


def is_bad_listing(url: str, title: Optional[str]):
    low = (url + " " + (title or "")).lower()
    bad_tokens = [
        "for-lease", "lease", "single-room", "single room", "roommate", "roommates",
        "pg", "hostel", "shared", "shared-room", "/review", "review", "project", "prjt"
    ]
    return any(t in low for t in bad_tokens)


# -----------------------------
# Build candidate society URLs
# -----------------------------
def build_society_url_candidates(society_raw: str, city_raw: str) -> List[str]:
    society = slugify(society_raw)
    city = slugify(city_raw)
    candidates = [
        f"https://www.nobroker.in/property/rent/{city}/{society}-{city}",
        f"https://www.nobroker.in/property/rent/{city}/{society}_{city}",
        f"https://www.nobroker.in/property/rent/{society}_{city}",
        f"https://www.nobroker.in/property/rent/{society}-{city}",
        f"https://www.nobroker.in/property/rent/{society}"
    ]
    # dedupe preserving order
    out = []
    seen = set()
    for u in candidates:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# -----------------------------
# HTTP fetch (async) with optional ScraperAPI proxying
# -----------------------------
async def fetch_text(client: httpx.AsyncClient, url: str) -> str:
    """
    Fetch page text with retries. If SCRAPERAPI_KEY is set, route via ScraperAPI.
    """
    target = url
    params = None
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    if SCRAPERAPI_KEY:
        # ScraperAPI format (scraperapi.com): https://api.scraperapi.com?api_key=KEY&url=<url>
        # If you use another scraping service, change accordingly.
        target = "http://api.scraperapi.com/"
        params = {"api_key": SCRAPERAPI_KEY, "url": url, "render": "false"}
        # don't add extra headers that might be blocked by the service
        headers = {"User-Agent": USER_AGENT}

    last_exc = None
    for attempt in range(1, RETRY_COUNT + 2):
        try:
            resp = await client.get(target, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_exc = e
            log(f"fetch_text: attempt {attempt} failed for {url}: {e}")
            await asyncio.sleep(0.5 * attempt)
    # if all retries failed, return empty string and log (caller should handle)
    log(f"fetch_text: all retries failed for {url}: {last_exc}")
    return ""


# -----------------------------
# Extract candidate listing URLs from a society page
# -----------------------------
def extract_listing_urls_from_html(html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    urls = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # take only property urls that contain for-rs- as we used before
        if "/property/" in href and "for-rs-" in href:
            full = href if href.startswith("http") else ("https://www.nobroker.in" + href)
            urls.add(full)
    return list(urls)


# -----------------------------
# DuckDuckGo fallback search
# -----------------------------
def duck_search_listings(society: str, city: str, max_results: int = 25) -> List[str]:
    q = f"{society} {city} for rent site:nobroker.in"
    log(f"DDG fallback search: {q}")
    listings = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(q, max_results=max_results):
                href = r.get("href")
                title = r.get("title") or ""
                if not href:
                    continue
                # ddgs sometimes wraps actual url in uddg= param
                href = re.sub(r"^.*uddg=", "", href) if "uddg=" in href else href
                href_low = href.lower()
                if "nobroker.in/property" not in href_low or "for-rs-" not in href_low:
                    continue
                if is_bad_listing(href, title):
                    continue
                listings.append(href)
    except Exception as e:
        log(f"duck_search_listings error: {e}")
    log(f"  DDG found {len(listings)} candidate listings")
    return listings


# -----------------------------
# Process listing pages (concurrently)
# -----------------------------
async def process_listing_urls(urls: List[str], society: str) -> Dict[str, int]:
    grouped = {}
    sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    async with httpx.AsyncClient() as client:

        async def handle_one(idx: int, url: str):
            nonlocal grouped
            async with sem:
                log(f"[{idx}/{len(urls)}] Fetching {url}")
                rent = extract_rent_from_url(url)
                html = await fetch_text(client, url)
                if not html:
                    log(f"  Failed to fetch {url}")
                    return
                soup = BeautifulSoup(html, "html.parser")
                title = soup.find("h1").get_text(strip=True) if soup.find("h1") else ""
                # minimal society match: check in title or url
                if society.lower() not in title.lower() and society.lower() not in url.lower():
                    log(f"  Skipped (not matching society): {url}")
                    # still continue, but skip
                    return
                bhk = extract_bhk_from_text(title) or extract_bhk_from_text(url)
                if rent is None:
                    rent = parse_int_from_text(html)
                if not bhk or rent is None:
                    log(f"  Skipped (missing bhk or rent): {url}")
                    return
                # sanity filters (same as earlier)
                if rent >= 500_000:
                    log(f"  Skipped (too high rent {rent})")
                    return
                try:
                    bhk_num = int(re.search(r"(\d+)", bhk).group(1))
                except:
                    bhk_num = None
                if bhk_num and bhk_num >= 2 and rent < 20000:
                    log(f"  Skipped (too low rent for {bhk} -> {rent})")
                    return
                if bhk_num == 1 and rent < 5000:
                    log(f"  Skipped (too low rent for 1 BHK -> {rent})")
                    return
                grouped.setdefault(bhk, []).append(rent)
                log(f"  Collected {bhk} -> ₹{rent:,}")

        tasks = [handle_one(i + 1, u) for i, u in enumerate(urls)]
        await asyncio.gather(*tasks)

    # choose best (max) per BHK
    best = {bhk: max(rents) for bhk, rents in grouped.items()}
    log(f"Best rents per BHK: {best}")
    return best


# -----------------------------
# Orchestrator
# -----------------------------
async def scrape_for_society(society: str, city: str):
    log(f"=== FETCH: {society}, {city} ===")
    candidates = build_society_url_candidates(society, city)
    all_urls = []
    async with httpx.AsyncClient() as client:
        for u in candidates:
            html = await fetch_text(client, u)
            urls = extract_listing_urls_from_html(html)
            log(f"  Candidate {u} found {len(urls)} listing URLs")
            if urls:
                all_urls.extend(urls)
                break

    # dedupe and fallback
    all_urls = list(dict.fromkeys(all_urls))
    if not all_urls:
        log("No society-page listings found, using DDG fallback")
        ddg_urls = duck_search_listings(society, city, max_results=30)
        all_urls.extend(ddg_urls)

    if not all_urls:
        log("No listings found even after DDG fallback")
        return {}

    best = await process_listing_urls(all_urls, society)
    return best


# -----------------------------
# FastAPI endpoint
# -----------------------------
@app.get("/rent")
async def get_rent(society: str = Query(...), city: str = Query(...)):
    try:
        best = await scrape_for_society(society, city)
        return JSONResponse({"society": society, "city": city, "total_results": len(best), "results": best})
    except Exception as e:
        log(f"get_rent error: {e}")
        raise HTTPException(500, detail=str(e))


@app.get("/")
def root():
    return {"status": "ok", "message": "Rent Scraper API (no-playwright) running."}


# Run locally: uvicorn main:app --host 0.0.0.0 --port 10000
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

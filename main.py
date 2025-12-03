import re
import asyncio
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
from ddgs import DDGS
from playwright.async_api import async_playwright

app = FastAPI()

# -----------------------------
# Utilities
# -----------------------------
def slugify(s: str) -> str:
    s = s.strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s)
    return s.strip('-')

def extract_bhk_from_text(text):
    if not text:
        return None
    m = re.search(r'(\d+)\s*[-]?\s*BHK', text, flags=re.IGNORECASE)
    if m:
        return f"{int(m.group(1))} BHK"
    return None

def parse_int_from_text(s):
    if not s:
        return None
    m = re.findall(r'₹\s*([0-9,]+)', s)
    if m:
        nums = [int(x.replace(',', '')) for x in m]
        return max(nums)
    m2 = re.findall(r'\b([0-9]{4,7})\b', s)
    if m2:
        nums = [int(x) for x in m2]
        return max(nums)
    return None

def extract_rent_from_url(url):
    m = re.search(r'for-rs-([0-9,]+)', url.replace(',', ''))
    if m:
        return int(m.group(1))
    return None

def is_bad_listing(url, title):
    low = (url + " " + (title or "")).lower()
    bad_tokens = ["for-lease", "lease", "single-room", "single room", "roommate", "roommates",
                  "pg", "hostel", "shared", "shared-room", "/review", "review", "project", "prjt"]
    return any(t in low for t in bad_tokens)

# -----------------------------
# Society URL candidates
# -----------------------------
def build_society_url_candidates(society_raw, city_raw):
    society = slugify(society_raw)
    city = slugify(city_raw)
    candidates = [
        f"https://www.nobroker.in/property/rent/{city}/{society}-{city}",
        f"https://www.nobroker.in/property/rent/{city}/{society}_{city}",
        f"https://www.nobroker.in/property/rent/{society}_{city}",
        f"https://www.nobroker.in/property/rent/{society}-{city}",
        f"https://www.nobroker.in/property/rent/{society}"
    ]
    # dedupe
    seen = set()
    out = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def extract_listing_urls_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/property/" in href and "for-rs-" in href:
            full = href if href.startswith("http") else ("https://www.nobroker.in" + href)
            urls.add(full)
    return list(urls)

# -----------------------------
# Async Playwright fetch
# -----------------------------
async def fetch_html(url):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=20000)
            content = await page.content()
        except Exception:
            content = ""
        await browser.close()
        return content

# -----------------------------
# DDG fallback
# -----------------------------
def duck_search_listings(society, city, max_results=25):
    q = f"{society} {city} for rent site:nobroker.in"
    listings = []
    with DDGS() as ddgs:
        for r in ddgs.text(q, max_results=max_results):
            href = r.get("href")
            title = r.get("title") or ""
            if not href:
                continue
            href = re.sub(r'^.*uddg=', '', href) if "uddg=" in href else href
            href_low = href.lower()
            if "nobroker.in/property" not in href_low or "for-rs-" not in href_low:
                continue
            if is_bad_listing(href, title):
                continue
            listings.append(href)
    return listings

# -----------------------------
# Process listings
# -----------------------------
async def process_listing_urls(urls, society):
    grouped = {}
    for i, url in enumerate(urls, start=1):
        rent = extract_rent_from_url(url)
        # fetch HTML
        html = await fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")
        title = soup.find("h1").get_text(strip=True) if soup.find("h1") else ""
        if society.lower() not in title.lower() and society.lower() not in url.lower():
            continue
        bhk = extract_bhk_from_text(title) or extract_bhk_from_text(url)
        if rent is None:
            rent = parse_int_from_text(html)
        if not bhk or rent is None:
            continue
        # sanity filters
        if rent >= 500_000:
            continue
        try:
            bhk_num = int(re.search(r'(\d+)', bhk).group(1))
        except:
            bhk_num = None
        if bhk_num and bhk_num >= 2 and rent < 20000:
            continue
        if bhk_num == 1 and rent < 5000:
            continue
        grouped.setdefault(bhk, []).append(rent)
    best = {bhk: max(rents) for bhk, rents in grouped.items()}
    return best

# -----------------------------
# Orchestrator
# -----------------------------
async def scrape_for_society(society, city):
    candidates = build_society_url_candidates(society, city)
    all_urls = []
    for u in candidates:
        html = await fetch_html(u)
        urls = extract_listing_urls_from_html(html)
        if urls:
            all_urls.extend(urls)
            break
    all_urls = list(dict.fromkeys(all_urls))  # dedupe
    if not all_urls:
        # DDG fallback
        ddg_urls = duck_search_listings(society, city, max_results=30)
        all_urls.extend(ddg_urls)
    if not all_urls:
        return {}
    best = await process_listing_urls(all_urls, society)
    return best

# -----------------------------
# FastAPI endpoint
# -----------------------------
@app.get("/rent")
async def get_rent(society: str = Query(...), city: str = Query(...)):
    best = await scrape_for_society(society, city)
    return JSONResponse({
        "society": society,
        "city": city,
        "total_results": len(best),
        "results": best
    })

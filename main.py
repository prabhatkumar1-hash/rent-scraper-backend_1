import os
import re
from urllib.parse import quote_plus
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY")

def wrap_url(url: str) -> str:
    """Route the request through ScraperAPI if key is present."""
    if not SCRAPERAPI_KEY:
        return url
    return f"http://api.scraperapi.com/?api_key={SCRAPERAPI_KEY}&url={quote_plus(url)}&render=true"

async def fetch_html(url: str, site_name: str) -> str:
    """Fetch page HTML with debug info."""
    real_url = wrap_url(url)
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            print(f"\n📡 Fetching {site_name}: {real_url}")
            r = await client.get(real_url, headers={"User-Agent": "Mozilla/5.0"})
            print(f"🔎 Status: {r.status_code}")
            if r.status_code != 200:
                print(f"❌ {site_name} returned status {r.status_code}")
                return ""
            if len(r.text.strip()) < 200:
                print(f"⚠️ {site_name}: HTML very short, probably blocked")
            print(f"HTML length {site_name}: {len(r.text)}")
            return r.text
        except Exception as e:
            print(f"❌ Error fetching {site_name}: {e}")
            return ""

# -----------------------------
# Scraper functions
# -----------------------------
async def scrape_nobroker(society, city):
    query = quote_plus(f"{society} {city}")
    url = f"https://www.nobroker.in/property/rent?searchParam={query}"
    html = await fetch_html(url, "NoBroker")
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("a[href*='/property/']") or []

    results = []
    for c in cards[:8]:
        try:
            title = c.get_text(" ", strip=True)
            link = c.get("href")
            if link and link.startswith("/"):
                link = "https://www.nobroker.in" + link
            price_match = re.search(r"₹\s*[\d,]+|\d+\s*k", title)
            bhk_match = re.search(r"(\d+)\s*BHK", title, re.I)
            results.append({
                "source": "NoBroker",
                "title": title[:240],
                "link": link,
                "price": int(price_match.group(0).replace("₹", "").replace(",", "").replace("k","000")) if price_match else None,
                "bhk": bhk_match.group(1) + " BHK" if bhk_match else None
            })
        except:
            continue
    print(f"🔵 NoBroker found: {len(results)} items")
    return results

async def scrape_magicbricks(society, city):
    query = quote_plus(f"{society} {city}")
    url = f"https://www.magicbricks.com/property-for-rent/residential-real-estate?keyword={query}"
    html = await fetch_html(url, "MagicBricks")
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.mb-srp__card, div.srpCard") or []

    results = []
    for c in cards[:8]:
        try:
            title = c.get_text(" ", strip=True)
            link = c.find("a")["href"] if c.find("a") else None
            price_match = re.search(r"₹\s*[\d,]+|\d+\s*k|Lac|Lakh", title, re.I)
            bhk_match = re.search(r"(\d+)\s*BHK", title, re.I)
            results.append({
                "source": "MagicBricks",
                "title": title[:240],
                "link": link,
                "price": int(price_match.group(0).replace("₹","").replace(",","").replace("k","000")) if price_match else None,
                "bhk": bhk_match.group(1) + " BHK" if bhk_match else None
            })
        except:
            continue
    print(f"🔴 MagicBricks found: {len(results)} items")
    return results

async def scrape_99acres(society, city):
    query = quote_plus(f"{society} {city}")
    url = f"https://www.99acres.com/search/property/rent?search_type=QS&keyword={query}"
    html = await fetch_html(url, "99acres")
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.srp-card, div.component-card") or []

    results = []
    for c in cards[:8]:
        try:
            text = c.get_text(" ", strip=True)
            price_match = re.search(r"₹[\d,]+", text)
            bhk_match = re.search(r"(\d+)\s*BHK", text)
            results.append({
                "source": "99acres",
                "title": text[:240],
                "link": None,
                "price": int(price_match.group(0).replace("₹","").replace(",","")) if price_match else None,
                "bhk": bhk_match.group(1) + " BHK" if bhk_match else None
            })
        except:
            continue
    print(f"🟠 99acres found: {len(results)} items")
    return results

async def scrape_housing(society, city):
    query = quote_plus(f"{society} {city}")
    url = f"https://housing.com/in/buy/search?query={query}"
    html = await fetch_html(url, "Housing.com")
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card, div.listing-card") or []

    results = []
    for c in cards[:8]:
        try:
            text = c.get_text(" ", strip=True)
            price_match = re.search(r"₹[\d,]+", text)
            bhk_match = re.search(r"(\d+)\s*BHK", text)
            results.append({
                "source": "Housing.com",
                "title": text[:240],
                "link": None,
                "price": int(price_match.group(0).replace("₹","").replace(",","")) if price_match else None,
                "bhk": bhk_match.group(1) + " BHK" if bhk_match else None
            })
        except:
            continue
    print(f"🟣 Housing found: {len(results)} items")
    return results

async def scrape_makaan(society, city):
    query = quote_plus(f"{society} {city}")
    url = f"https://www.makaan.com/for-rent/residential?keyword={query}"
    html = await fetch_html(url, "Makaan")
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card, div.listing, div.property-card") or []

    results = []
    for c in cards[:8]:
        try:
            text = c.get_text(" ", strip=True)
            price_match = re.search(r"₹[\d,]+", text)
            bhk_match = re.search(r"(\d+)\s*BHK", text)
            results.append({
                "source": "Makaan",
                "title": text[:240],
                "link": None,
                "price": int(price_match.group(0).replace("₹","").replace(",","")) if price_match else None,
                "bhk": bhk_match.group(1) + " BHK" if bhk_match else None
            })
        except:
            continue
    print(f"🟢 Makaan found: {len(results)} items")
    return results

# -----------------------------
# API endpoint
# -----------------------------
@app.get("/rent")
async def get_rent(
    society: str = Query(...),
    city: str = Query(...)
):
    print(f"\n=== 🏙 FETCHING FOR: {society}, {city} ===")
    results = []

    scrapers = [
        scrape_nobroker,
        scrape_magicbricks,
        scrape_99acres,
        scrape_housing,
        scrape_makaan
    ]

    for scraper in scrapers:
        try:
            res = await scraper(society, city)
            results.extend(res)
        except Exception as e:
            print(f"❌ Error in {scraper.__name__}: {e}")

    return JSONResponse({
        "society": society,
        "city": city,
        "total_results": len(results),
        "results": results
    })

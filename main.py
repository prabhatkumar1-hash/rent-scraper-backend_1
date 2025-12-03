import os
import re
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
    return f"http://api.scraperapi.com/?api_key={SCRAPERAPI_KEY}&url={url}&render=true"

async def fetch_html(url: str) -> str:
    """Fetch page HTML with debug info."""
    real_url = wrap_url(url)
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            print(f"📡 Fetching: {real_url}")
            r = await client.get(real_url, headers={"User-Agent": "Mozilla/5.0"})
            print(f"🔎 Status: {r.status_code}")

            if r.status_code == 403:
                print("❌ Blocked (403 Forbidden)")
            if len(r.text.strip()) < 200:
                print("❗ Warning: HTML is VERY short — probably blocked")

            return r.text
        except Exception as e:
            print(f"❌ Error fetching {url}: {e}")
            return ""

# ------------------------------------------
# 🔵 1. NoBroker scraper
# ------------------------------------------
async def scrape_nobroker(society, city):
    query = society.replace(" ", "-")
    url = f"https://www.nobroker.in/property/rent/{city}/{query}"
    html = await fetch_html(url)

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card, div.NB-card, div.nb__3q46n")

    results = []
    for c in cards:
        price = c.text if "₹" in c.text else None
        bhk = re.findall(r"(\d+)\s*BHK", c.text)
        results.append({
            "source": "NoBroker",
            "price": price,
            "bhk": bhk[0] if bhk else None
        })

    print(f"🔵 NoBroker found: {len(results)} items")
    return results


# ------------------------------------------
# 🔴 2. MagicBricks scraper
# ------------------------------------------
async def scrape_magicbricks(society, city):
    url = f"https://www.magicbricks.com/property-for-rent/residential-real-estate?keyword={society}%20{city}"
    html = await fetch_html(url)

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.mb-srp__card, div.srpCard")

    results = []
    for c in cards:
        price = c.find(text=re.compile("₹"))
        bhk = c.find(text=re.compile("BHK"))
        results.append({
            "source": "MagicBricks",
            "price": price.strip() if price else None,
            "bhk": bhk.strip() if bhk else None
        })

    print(f"🔴 MagicBricks found: {len(results)} items")
    return results


# ------------------------------------------
# 🟠 3. 99acres scraper
# ------------------------------------------
async def scrape_99acres(society, city):
    url = f"https://www.99acres.com/search/property/rent/residential-all/{society}-{city}"
    html = await fetch_html(url)

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.srp-card, div.component-card")

    results = []
    for c in cards:
        text = c.get_text(" ", strip=True)
        bhk = re.findall(r"(\d+)\s*BHK", text)
        price = re.findall(r"₹[\d,]+", text)
        results.append({
            "source": "99acres",
            "price": price[0] if price else None,
            "bhk": bhk[0] if bhk else None
        })

    print(f"🟠 99acres found: {len(results)} items")
    return results


# ------------------------------------------
# 🟣 4. Housing.com scraper
# ------------------------------------------
async def scrape_housing(society, city):
    url = f"https://housing.com/rent/search-{city}?query={society}"
    html = await fetch_html(url)

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card, div.list-card")

    results = []
    for c in cards:
        text = c.get_text(" ", strip=True)
        bhk = re.findall(r"(\d+)\s*BHK", text)
        price = re.findall(r"₹[\d,]+", text)
        results.append({
            "source": "Housing.com",
            "price": price[0] if price else None,
            "bhk": bhk[0] if bhk else None
        })

    print(f"🟣 Housing found: {len(results)} items")
    return results


# ------------------------------------------
# 🟢 5. Makaan scraper
# ------------------------------------------
async def scrape_makaan(society, city):
    url = f"https://www.makaan.com/{city}-rentals/{society}"
    html = await fetch_html(url)

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.cardLayout, div.listCard")

    results = []
    for c in cards:
        text = c.get_text(" ", strip=True)
        bhk = re.findall(r"(\d+)\s*BHK", text)
        price = re.findall(r"₹[\d,]+", text)
        results.append({
            "source": "Makaan",
            "price": price[0] if price else None,
            "bhk": bhk[0] if bhk else None
        })

    print(f"🟢 Makaan found: {len(results)} items")
    return results


# ------------------------------------------
# 🚀 MAIN API ENDPOINT
# ------------------------------------------
@app.get("/rent")
async def get_rent(
    society: str = Query(...),
    city: str = Query(...)
):
    society_lower = society.lower().strip()
    city_lower = city.lower().strip()

    print(f"\n=== 🏙 FETCHING FOR: {society_lower}, {city_lower} ===")

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
            res = await scraper(society_lower, city_lower)
            results.extend(res)
        except Exception as e:
            print(f"❌ Error in {scraper.__name__}: {e}")

    return JSONResponse({
        "society": society_lower,
        "city": city_lower,
        "total_results": len(results),
        "results": results
    })

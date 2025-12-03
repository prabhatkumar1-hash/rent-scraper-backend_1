import os
import httpx
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI(title="Society Rent Aggregator (NoBroker Only)")

# Optional ScraperAPI key
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY")

def wrap_url(url: str) -> str:
    """Route request through ScraperAPI if key is present."""
    if not SCRAPERAPI_KEY:
        return url
    from urllib.parse import quote_plus
    return f"http://api.scraperapi.com/?api_key={SCRAPERAPI_KEY}&url={quote_plus(url)}&render=true"

async def fetch_nobroker_json(society: str, city: str):
    """
    Fetch listings from NoBroker JSON API.
    Returns list of dicts with title, price, bhk, link.
    """
    search_text = f"{society} {city}"
    url = f"https://www.nobroker.in/api/v1/property/search?searchParam={search_text}"
    url = wrap_url(url)
    
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            print(f"📡 Fetching NoBroker JSON: {url}")
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                print(f"❌ NoBroker returned status {r.status_code}")
                return []
            data = r.json()
            listings = []
            for prop in data.get("props", [])[:20]:
                # Extract relevant info
                title = prop.get("displayName") or prop.get("projectTitle") or "No title"
                link = f"https://www.nobroker.in/property/{prop.get('slug')}" if prop.get("slug") else None
                price = prop.get("rent") or None
                bhk = prop.get("bedrooms") or None
                if bhk:
                    bhk = f"{bhk} BHK"
                listings.append({
                    "source": "NoBroker",
                    "title": title,
                    "link": link,
                    "price": price,
                    "bhk": bhk
                })
            print(f"🔵 NoBroker found: {len(listings)} items")
            return listings
        except Exception as e:
            print(f"❌ Error fetching NoBroker JSON: {e}")
            return []

@app.get("/rent")
async def get_rent(society: str = Query(...), city: str = Query(...)):
    print(f"\n=== 🏙 FETCHING FOR: {society}, {city} ===")
    results = await fetch_nobroker_json(society, city)

    return JSONResponse({
        "society": society,
        "city": city,
        "total_results": len(results),
        "results": results
    })

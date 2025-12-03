# main.py
import os
import re
import asyncio
from typing import List, Dict, Any, Optional

import httpx
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup

# ---- Config ----
PORT = int(os.getenv("PORT", "10000"))
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY")  # optional
REQUEST_TIMEOUT = 15.0
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

app = FastAPI(title="Society Rent Aggregator", version="1.0")

# ---- Response model ----
class Listing(BaseModel):
    site: str
    bhk: Optional[str] = None
    price: Optional[int] = None
    price_text: Optional[str] = None
    area: Optional[str] = None
    title: Optional[str] = None
    link: Optional[str] = None

class RentResponse(BaseModel):
    society: str
    city: Optional[str] = None
    results: List[Listing]

# ---- Helper utilities ----
def build_scraperapi_url(target_url: str) -> str:
    """If SCRAPERAPI_KEY is provided, return the ScraperAPI wrapped URL."""
    if not SCRAPERAPI_KEY:
        return target_url
    # ScraperAPI standard URL form: http://api.scraperapi.com?api_key=KEY&url=<url>
    from urllib.parse import quote_plus
    return f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={quote_plus(target_url)}&render=true"

async def fetch_html(client: httpx.AsyncClient, url: str) -> str:
    url = build_scraperapi_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    try:
        r = await client.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.text
    except Exception as e:
        # If ScraperAPI used and failed, bubble up so caller can decide
        raise

def parse_price_int(text: str) -> Optional[int]:
    if not text:
        return None
    # normalize numbers like "₹ 32,000", "32,000 / month", "32k"
    txt = text.replace(",", "").lower()
    m = re.search(r"(\d+)(k)?", txt)
    if not m:
        return None
    val = int(m.group(1))
    if m.group(2) == 'k':
        val *= 1000
    return val

# ---- Per-site scraping functions (simple conservative parsers) ----

async def fetch_nobroker(client: httpx.AsyncClient, society: str, city: Optional[str]) -> List[Dict[str, Any]]:
    """
    Query NoBroker's public search page and extract some cards.
    Note: NoBroker has JSON endpoints sometimes; here we use HTML parsing for safety.
    """
    q = f"{society} {city or ''}".strip().replace(" ", "+")
    url = f"https://www.nobroker.in/property/rent?searchParam={q}"
    try:
        html = await fetch_html(client, url)
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    results = []
    # Look for card elements - fallback approaches
    cards = soup.select(".card, .list-card, .nb__card") or soup.select("a[href*='/property/']")
    for c in cards[:8]:
        try:
            title = c.get_text(separator=" ", strip=True)[:240]
            link = c.find("a")
            link_url = "https://www.nobroker.in" + link["href"] if link and link.get("href", "").startswith("/") else (link["href"] if link else None)
            price_text = ""
            # try to find price-like text inside card
            pt = c.find(string=re.compile(r"₹|Rs|INR|\d+\s*k", re.I))
            if pt:
                price_text = pt.strip()
            else:
                # fallback: any number in text
                m = re.search(r"₹\s?[\d,]+", title)
                price_text = m.group(0) if m else None
            bhk = None
            m_bhk = re.search(r"(\d+)\s*BHK", title, re.I)
            if m_bhk:
                bhk = m_bhk.group(1) + " BHK"
            price = parse_price_int(price_text or "")
            results.append({
                "site": "NoBroker",
                "title": title,
                "link": link_url,
                "price_text": price_text,
                "price": price,
                "bhk": bhk
            })
        except Exception:
            continue
    return results

async def fetch_magicbricks(client: httpx.AsyncClient, society: str, city: Optional[str]) -> List[Dict[str, Any]]:
    q = f"{society} {city or ''}".strip().replace(" ", "%20")
    url = f"https://www.magicbricks.com/property-for-rent/residential-real-estate?proptype=Multistorey-Apartment,Builder-Floor-Apartment&keyword={q}"
    try:
        html = await fetch_html(client, url)
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    results = []
    cards = soup.select(".m-srp-card, .mb-srp-card, .srpTuple") or soup.select("a[href*='/property/']")
    for c in cards[:8]:
        try:
            title = c.get_text(separator=" ", strip=True)[:240]
            link = c.find("a")
            link_url = "https://www.magicbricks.com" + link["href"] if link and link.get("href", "").startswith("/") else (link["href"] if link else None)
            price_text = ""
            pt = c.find(string=re.compile(r"₹|Lakh|lac|k", re.I))
            if pt:
                price_text = pt.strip()
            bhk = None
            m_bhk = re.search(r"(\d+)\s*BHK|(\d+)\s*bhk", title, re.I)
            if m_bhk:
                bhk = (m_bhk.group(1) or m_bhk.group(2)) + " BHK"
            price = parse_price_int(price_text or "")
            results.append({
                "site": "MagicBricks",
                "title": title,
                "link": link_url,
                "price_text": price_text,
                "price": price,
                "bhk": bhk
            })
        except Exception:
            continue
    return results

async def fetch_99acres(client: httpx.AsyncClient, society: str, city: Optional[str]) -> List[Dict[str, Any]]:
    q = f"{society} {city or ''}".strip().replace(" ", "+")
    url = f"https://www.99acres.com/search/property/rent?search_type=QS&keyword={q}"
    try:
        html = await fetch_html(client, url)
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    results = []
    cards = soup.select(".srpTuple__tupleWrap, .result-card, .srpCard") or soup.select("a[href*='property.99acres.com']")
    for c in cards[:8]:
        try:
            title = c.get_text(separator=" ", strip=True)[:240]
            link = c.find("a")
            link_url = link["href"] if link and link.get("href") else None
            price_text = ""
            pt = c.find(string=re.compile(r"₹|\d+\s*k|\d+\,\d+", re.I))
            if pt:
                price_text = pt.strip()
            bhk = None
            m = re.search(r"(\d+)\s*BHK", title, re.I)
            if m:
                bhk = m.group(1) + " BHK"
            price = parse_price_int(price_text or "")
            results.append({
                "site": "99acres",
                "title": title,
                "link": link_url,
                "price_text": price_text,
                "price": price,
                "bhk": bhk
            })
        except Exception:
            continue
    return results

async def fetch_housing(client: httpx.AsyncClient, society: str, city: Optional[str]) -> List[Dict[str, Any]]:
    q = f"{society} {city or ''}".strip().replace(" ", "+")
    url = f"https://housing.com/in/buy/search?query={q}"
    try:
        html = await fetch_html(client, url)
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    results = []
    cards = soup.select(".listing, .card, .listing-card") or soup.select("a[href*='/property/']")
    for c in cards[:8]:
        try:
            title = c.get_text(separator=" ", strip=True)[:240]
            link = c.find("a")
            link_url = "https://housing.com" + link["href"] if link and link.get("href", "").startswith("/") else (link["href"] if link else None)
            price_text = ""
            pt = c.find(string=re.compile(r"₹|per month|Lakh|lac", re.I))
            if pt:
                price_text = pt.strip()
            bhk = None
            m = re.search(r"(\d+)\s*BHK", title, re.I)
            if m:
                bhk = m.group(1) + " BHK"
            price = parse_price_int(price_text or "")
            results.append({
                "site": "Housing",
                "title": title,
                "link": link_url,
                "price_text": price_text,
                "price": price,
                "bhk": bhk
            })
        except Exception:
            continue
    return results

async def fetch_makaan(client: httpx.AsyncClient, society: str, city: Optional[str]) -> List[Dict[str, Any]]:
    q = f"{society} {city or ''}".strip().replace(" ", "%20")
    url = f"https://www.makaan.com/for-rent/residential?keyword={q}"
    try:
        html = await fetch_html(client, url)
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    results = []
    cards = soup.select(".card, .listing, .property-card") or soup.select("a[href*='/property/']")
    for c in cards[:8]:
        try:
            title = c.get_text(separator=" ", strip=True)[:240]
            link = c.find("a")
            link_url = "https://www.makaan.com" + link["href"] if link and link.get("href", "").startswith("/") else (link["href"] if link else None)
            price_text = ""
            pt = c.find(string=re.compile(r"₹|Lakh|lac|\d+\s*k", re.I))
            if pt:
                price_text = pt.strip()
            bhk = None
            m = re.search(r"(\d+)\s*BHK", title, re.I)
            if m:
                bhk = m.group(1) + " BHK"
            price = parse_price_int(price_text or "")
            results.append({
                "site": "Makaan",
                "title": title,
                "link": link_url,
                "price_text": price_text,
                "price": price,
                "bhk": bhk
            })
        except Exception:
            continue
    return results

# ---- Aggregator endpoint ----

@app.get("/rent", response_model=RentResponse)
async def get_rent(society: str = Query(..., min_length=2), city: Optional[str] = Query(None)):
    """
    Aggregate rent listings from multiple sites for a given society (and optional city).
    Response: JSON array of normalized listing objects.
    """
    async with httpx.AsyncClient() as client:
        tasks = [
            fetch_nobroker(client, society, city),
            fetch_magicbricks(client, society, city),
            fetch_99acres(client, society, city),
            fetch_housing(client, society, city),
            fetch_makaan(client, society, city),
        ]
        # Run in parallel
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for res in all_results:
        if isinstance(res, Exception):
            # skip failing site, but log to console
            print("Site fetch error:", str(res))
            continue
        for item in res:
            # normalize to Listing
            listing = Listing(
                site=item.get("site"),
                bhk=item.get("bhk"),
                price=item.get("price"),
                price_text=item.get("price_text"),
                area=item.get("area"),
                title=item.get("title"),
                link=item.get("link")
            )
            results.append(listing.dict())

    # sort by price if numeric
    results_sorted = sorted(results, key=lambda x: x.get("price") or 10**12)

    return RentResponse(society=society, city=city, results=results_sorted)

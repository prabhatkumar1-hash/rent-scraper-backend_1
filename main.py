from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import asyncio
from playwright.async_api import async_playwright
import urllib.parse

app = FastAPI(title="Rent Scraper API")


# -------------------------------
# Fetch HTML using Playwright
# -------------------------------
async def fetch_html(url: str) -> str:
    print("🌐 Fetching:", url)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage"
            ]
        )

        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(url, timeout=60000, wait_until="domcontentloaded")

        html = await page.content()
        await browser.close()

        return html


# -------------------------------
# Example Scraper
# -------------------------------
async def scrape_for_society(society: str, city: str):
    query = urllib.parse.quote(society)
    city_enc = urllib.parse.quote(city)

    # Replace with your real rent URL
    url = f"https://example.com/rent?society={query}&city={city_enc}"

    html = await fetch_html(url)

    return {
        "society": society,
        "city": city,
        "length": len(html),
        "status": "success"
    }


# -------------------------------
# API Endpoint
# -------------------------------
@app.get("/rent")
async def get_rent(society: str, city: str):
    try:
        result = await scrape_for_society(society, city)
        return JSONResponse(content=result)

    except Exception as e:
        print("🔥 ERROR:", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------
# Health Check
# -------------------------------
@app.get("/")
def home():
    return {"status": "ok"}


# -------------------------------
# Local Development
# -------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000, reload=True)

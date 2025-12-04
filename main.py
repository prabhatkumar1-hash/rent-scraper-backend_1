from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright
import urllib.parse

app = FastAPI(title="Rent Scraper")

# -------------------------------
# UTILITY: Fetch HTML for a URL
# -------------------------------
async def fetch_html(url: str) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle")
        html = await page.content()
        await browser.close()
        return html

# -------------------------------
# SCRAPE LOGIC (example)
# -------------------------------
async def scrape_for_society(society: str, city: str):
    query = urllib.parse.quote(society)
    city_enc = urllib.parse.quote(city)
    
    # Replace with your real scraping URL
    url = f"https://example.com/rent?society={query}&city={city_enc}"

    html = await fetch_html(url)
    return {
        "society": society,
        "city": city,
        "html_length": len(html)
    }

# -------------------------------
# API ENDPOINT
# -------------------------------
@app.get("/rent")
async def get_rent(
    society: str = Query(..., description="Name of the society"),
    city: str = Query(..., description="City name")
):
    try:
        result = await scrape_for_society(society, city)
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------------
# HEALTH CHECK
# -------------------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Rent Scraper API is running."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000, reload=True)

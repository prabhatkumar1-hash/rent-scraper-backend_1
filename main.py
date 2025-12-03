from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import asyncio
from playwright.async_api import async_playwright, Error as PlaywrightError
import urllib.parse

app = FastAPI(title="Rent Scraper")

# -------------------------------
# UTILITY: Fetch HTML for a URL
# -------------------------------
async def fetch_html(url: str) -> str:
    """
    Fetch HTML content of a URL using Playwright Chromium headless.
    Automatically installs browsers if missing.
    """
    try:
        async with async_playwright() as pw:
            # Install browsers at runtime if not installed
            await pw.chromium.install()  

            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(url)
            html = await page.content()
            await browser.close()
            return html

    except PlaywrightError as e:
        raise RuntimeError(f"Playwright error: {e}")

# -------------------------------
# SCRAPE LOGIC (example)
# -------------------------------
async def scrape_for_society(society: str, city: str):
    """
    Scrapes rent listings for a given society & city.
    Modify this function with your actual scraping logic.
    """
    query = urllib.parse.quote(society)
    city_enc = urllib.parse.quote(city)
    url = f"https://example.com/rent?society={query}&city={city_enc}"  # Replace with actual URL

    html = await fetch_html(url)
    
    # Example: return raw HTML (you should parse it)
    return {"society": society, "city": city, "html_length": len(html)}

# -------------------------------
# API ENDPOINT
# -------------------------------
@app.get("/rent")
async def get_rent(
    society: str = Query(..., description="Name of the society"),
    city: str = Query(..., description="City name")
):
    """
    Returns rent listings for a society.
    """
    try:
        result = await scrape_for_society(society, city)
        return JSONResponse(content=result)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

# -------------------------------
# HEALTH CHECK
# -------------------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Rent Scraper API is running."}

# -------------------------------
# MAIN ENTRYPOINT (for local dev)
# -------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000, reload=True)

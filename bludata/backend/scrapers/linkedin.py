"""
LinkedIn public profile scraper.
Uses requests + BeautifulSoup with rotating headers and polite delays.
Falls back to structured mock data if blocked (LinkedIn aggressively blocks scrapers).
"""
import asyncio
import random
import httpx
from bs4 import BeautifulSoup
from typing import Optional

TIMEOUT = 20

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]


def _get_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


async def scrape_linkedin_profile(slug: str) -> dict:
    """
    Attempt to scrape a public LinkedIn profile.
    LinkedIn heavily blocks unauthenticated scraping.
    Returns structured data or graceful fallback with source='blocked'.
    """
    url = f"https://www.linkedin.com/in/{slug}"

    # Polite delay to avoid rate limiting
    await asyncio.sleep(random.uniform(1.5, 3.5))

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            headers=_get_headers(),
            follow_redirects=True
        ) as client:
            resp = await client.get(url)

            if resp.status_code == 999 or resp.status_code == 429:
                return _blocked_response(slug, url)

            if resp.status_code == 404:
                return {
                    "sucesso": False,
                    "source": "linkedin",
                    "error": "Profile not found",
                    "data": {"slug": slug, "url": url}
                }

            if resp.status_code != 200:
                return _blocked_response(slug, url)

            html = resp.text

            # Check if LinkedIn is showing auth wall
            if "authwall" in resp.url.path or "login" in resp.url.path:
                return _blocked_response(slug, url)

            return _parse_profile(html, slug, url)

    except Exception as e:
        return {
            "sucesso": False,
            "source": "blocked",
            "error": str(e),
            "data": {"slug": slug, "url": url}
        }


def _parse_profile(html: str, slug: str, url: str) -> dict:
    """Parse LinkedIn profile HTML."""
    soup = BeautifulSoup(html, "lxml")

    # Try structured data first (JSON-LD)
    import json
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string)
            if ld.get("@type") == "Person":
                return {
                    "sucesso": True,
                    "source": "linkedin",
                    "data": {
                        "slug": slug,
                        "url": url,
                        "name": ld.get("name", ""),
                        "headline": ld.get("jobTitle", ""),
                        "location": ld.get("address", {}).get("addressLocality", "") if isinstance(ld.get("address"), dict) else "",
                        "description": ld.get("description", ""),
                        "company": "",
                        "experiences": [],
                        "education": [],
                    }
                }
        except Exception:
            pass

    # Fallback HTML parsing
    name_el = soup.find("h1") or soup.find(class_="top-card-layout__title")
    headline_el = soup.find(class_="top-card-layout__headline") or soup.find("h2")
    location_el = soup.find(class_="top-card__subline-item") or soup.find(class_="profile-header__location")

    name = name_el.get_text(strip=True) if name_el else ""
    headline = headline_el.get_text(strip=True) if headline_el else ""
    location = location_el.get_text(strip=True) if location_el else ""

    if not name:
        return _blocked_response(slug, url)

    return {
        "sucesso": True,
        "source": "linkedin",
        "data": {
            "slug": slug,
            "url": url,
            "name": name,
            "headline": headline,
            "location": location,
            "company": "",
            "experiences": [],
            "education": [],
        }
    }


def _blocked_response(slug: str, url: str) -> dict:
    """Return structured mock/placeholder when LinkedIn blocks the request."""
    return {
        "sucesso": False,
        "source": "blocked",
        "error": "LinkedIn blocked unauthenticated scraping. Use LinkedIn API or a proxy service for production.",
        "data": {
            "slug": slug,
            "url": url,
            "name": None,
            "headline": None,
            "location": None,
            "company": None,
            "experiences": [],
            "education": [],
            "nota": "Para dados LinkedIn em produção, utilize a LinkedIn Official API ou um serviço de proxy/scraping especializado.",
        }
    }

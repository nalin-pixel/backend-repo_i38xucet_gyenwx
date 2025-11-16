import os
import time
from typing import List, Dict
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlparse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}

@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    
    try:
        # Try to import database module
        from database import db
        
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            
            # Try to list collections to verify connectivity
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]  # Show first 10 collections
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
            
    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    
    # Check environment variables
    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    
    return response

# ---------- News Aggregation ----------
_FEEDS = [
    "https://thehackernews.com/feeds/posts/default",  # The Hacker News
    "https://krebsonsecurity.com/feed/",              # Krebs on Security
    "https://www.darkreading.com/rss.xml",            # Dark Reading
    "https://feeds.feedburner.com/OpenAIBlog",        # OpenAI Blog
    "https://www.schneier.com/feed/atom/",            # Schneier on Security
]

_news_cache: Dict[str, object] = {"ts": 0, "items": []}
_CACHE_TTL = 60 * 10  # 10 minutes


def _parse_date(text: str) -> float:
    try:
        # Try common RSS/Atom formats
        for fmt in [
            "%a, %d %b %Y %H:%M:%S %z",  # RFC822 e.g. Tue, 14 Nov 2023 10:00:00 +0000
            "%Y-%m-%dT%H:%M:%S%z",       # 2023-11-14T10:00:00+00:00
            "%Y-%m-%dT%H:%M:%SZ",        # 2023-11-14T10:00:00Z
        ]:
            try:
                return datetime.strptime(text, fmt).timestamp()
            except Exception:
                pass
    except Exception:
        pass
    return 0.0


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _fetch_feed(url: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        root = ET.fromstring(r.content)

        # Detect namespaces
        ns = {}
        for k, v in root.attrib.items():
            ns[k] = v

        # RSS (channel/item)
        channel = root.find('channel')
        if channel is not None:
            for item in channel.findall('item'):
                title = (item.findtext('title') or '').strip()
                link = (item.findtext('link') or '').strip()
                pub = item.findtext('pubDate') or item.findtext('date') or ''
                ts = _parse_date(pub)
                if title and link:
                    items.append({
                        "title": title,
                        "link": link,
                        "published": pub,
                        "timestamp": ts,
                        "source": _domain(link) or _domain(url)
                    })
            return items

        # Atom (entry)
        for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
            title_el = entry.find('{http://www.w3.org/2005/Atom}title')
            link_el = entry.find('{http://www.w3.org/2005/Atom}link')
            updated_el = entry.find('{http://www.w3.org/2005/Atom}updated')
            title = (title_el.text if title_el is not None else '').strip()
            link = (link_el.get('href') if link_el is not None else '').strip()
            pub = (updated_el.text if updated_el is not None else '')
            ts = _parse_date(pub)
            if title and link:
                items.append({
                    "title": title,
                    "link": link,
                    "published": pub,
                    "timestamp": ts,
                    "source": _domain(link) or _domain(url)
                })
        return items
    except Exception:
        return []


@app.get("/api/news")
def get_news(limit: int = 12):
    now = time.time()
    if now - _news_cache.get("ts", 0) < _CACHE_TTL and _news_cache.get("items"):
        items = _news_cache["items"]
    else:
        all_items: List[Dict[str, str]] = []
        for feed in _FEEDS:
            all_items.extend(_fetch_feed(feed))
        # Sort by timestamp desc (fallback to order)
        items = sorted(all_items, key=lambda x: x.get("timestamp", 0), reverse=True)
        # Deduplicate by link
        seen = set()
        deduped = []
        for it in items:
            link = it.get("link")
            if link and link not in seen:
                seen.add(link)
                deduped.append(it)
        items = deduped
        _news_cache["items"] = items
        _news_cache["ts"] = now

    return {"items": items[: max(1, min(50, limit))]}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

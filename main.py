import os
import time
import json
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse

import requests
import xml.etree.ElementTree as ET
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, EmailStr
from jose import JWTError, jwt
from passlib.context import CryptContext

# Database helpers
from database import create_document, get_documents, db

# ---------- App & Config ----------
app = FastAPI(title="SentinelAI Backend", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
WAITLIST_FILE = DATA_DIR / "waitlist.json"
SAMPLE_REPORT = STATIC_DIR / "sample_report.pdf"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change")
JWT_ALG = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# ---------- Models ----------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    sub: str
    email: EmailStr

class SignupBody(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None
    plan: Optional[str] = "individual"

class LoginBody(BaseModel):
    email: EmailStr
    password: str

class WaitlistEntry(BaseModel):
    email: EmailStr

class RepoConnectBody(BaseModel):
    repo_full_name: str

# ---------- Utils ----------

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(p: str) -> str:
    return pwd_context.hash(p)


async def get_current_user(request: Request):
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        email = payload.get("email")
        sub = payload.get("sub")
        if not email or not sub:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"id": sub, "email": email}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ---------- Basic ----------
@app.get("/")
def root():
    return {"message": "SentinelAI Backend running"}

@app.get("/test")
def test():
    return {
        "backend": "✅ Running",
        "database": "✅ Connected" if db is not None else "❌ Not Available",
        "has_report": SAMPLE_REPORT.exists(),
    }

# ---------- Waitlist & Report ----------

def load_waitlist() -> List[str]:
    if WAITLIST_FILE.exists():
        try:
            with open(WAITLIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            return []
    return []


def save_waitlist(emails: List[str]) -> None:
    with open(WAITLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(emails, f, indent=2)


@app.post("/api/waitlist")
def join_waitlist(entry: WaitlistEntry):
    email = entry.email.lower()
    emails = load_waitlist()
    if email in emails:
        return {"status": "exists", "message": "You're already on the list."}
    emails.append(email)
    save_waitlist(emails)
    return {"status": "ok", "message": "Thanks! You're on the early access list."}


@app.get("/api/report")
def get_report():
    if not SAMPLE_REPORT.exists():
        raise HTTPException(status_code=404, detail="Sample report not found")
    return FileResponse(path=str(SAMPLE_REPORT), media_type="application/pdf", filename="SentinelAI_Sample_Report.pdf")

# ---------- News Aggregation with Pagination ----------
_FEEDS = [
    "https://thehackernews.com/feeds/posts/default",
    "https://krebsonsecurity.com/feed/",
    "https://www.darkreading.com/rss.xml",
    "https://feeds.feedburner.com/OpenAIBlog",
    "https://www.schneier.com/feed/atom/",
]

_news_cache: Dict[str, object] = {"ts": 0, "items": []}
_CACHE_TTL = 60 * 10  # 10 minutes


def _parse_date(text: str) -> float:
    try:
        for fmt in [
            "%a, %d %b %Y %H:%M:%S %z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
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
def get_news(page: int = 1, page_size: int = 12):
    page = max(1, page)
    page_size = max(1, min(50, page_size))
    now = time.time()
    if now - _news_cache.get("ts", 0) >= _CACHE_TTL or not _news_cache.get("items"):
        all_items: List[Dict[str, str]] = []
        for feed in _FEEDS:
            all_items.extend(_fetch_feed(feed))
        items = sorted(all_items, key=lambda x: x.get("timestamp", 0), reverse=True)
        seen = set()
        deduped = []
        for it in items:
            link = it.get("link")
            if link and link not in seen:
                seen.add(link)
                deduped.append(it)
        _news_cache["items"] = deduped
        _news_cache["ts"] = now

    items = _news_cache["items"]
    start = (page - 1) * page_size
    end = start + page_size
    has_more = end < len(items)
    return {"items": items[start:end], "page": page, "page_size": page_size, "has_more": has_more, "total": len(items)}

# ---------- Auth (email/password + GitHub OAuth) ----------

# Collections: account, repoconnection

def _find_account_by_email(email: str) -> Optional[dict]:
    docs = get_documents("account", {"email": email.lower()}, limit=1)
    return docs[0] if docs else None


def _find_account_by_id(id_str: str) -> Optional[dict]:
    from bson import ObjectId
    try:
        docs = get_documents("account", {"_id": ObjectId(id_str)}, limit=1)
        return docs[0] if docs else None
    except Exception:
        return None


@app.post("/api/auth/signup", response_model=Token)
def signup(body: SignupBody):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    if _find_account_by_email(body.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    acc = {
        "email": body.email.lower(),
        "hashed_password": hash_password(body.password),
        "name": body.name,
        "plan": body.plan if body.plan in ("individual", "team") else "individual",
        "provider": "password",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    from pymongo import ReturnDocument
    inserted_id = db["account"].insert_one(acc).inserted_id
    access = create_access_token({"sub": str(inserted_id), "email": body.email.lower()})
    return Token(access_token=access)


@app.post("/api/auth/login", response_model=Token)
def login(body: LoginBody):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    acc = _find_account_by_email(body.email)
    if not acc or not verify_password(body.password, acc.get("hashed_password", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access = create_access_token({"sub": str(acc["_id"]), "email": acc["email"]})
    return Token(access_token=access)


@app.get("/api/auth/me")
def me(user=Depends(get_current_user)):
    acc = _find_account_by_id(user["id"]) or {}
    # remove sensitive fields
    if acc.get("hashed_password"):
        acc["hashed_password"] = "***"
    acc["_id"] = str(acc.get("_id")) if acc.get("_id") else None
    return {"user": acc}


@app.get("/api/auth/github/url")
def github_url():
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=400, detail="GitHub OAuth not configured")
    redirect_uri = f"{BACKEND_URL}/api/auth/github/callback"
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "read:user repo",
        "allow_signup": "true",
    }
    url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    return {"url": url}


@app.get("/api/auth/github/callback")
def github_callback(code: str):
    if not (GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET):
        raise HTTPException(status_code=400, detail="GitHub OAuth not configured")
    token_res = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
        },
        timeout=10,
    )
    token_res.raise_for_status()
    token_json = token_res.json()
    access_token = token_json.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="GitHub token exchange failed")

    user_res = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
        timeout=10,
    )
    user_res.raise_for_status()
    gh = user_res.json()
    email = (gh.get("email") or f"{gh.get('id')}@users.noreply.github.com").lower()

    # Upsert account by email
    existing = _find_account_by_email(email)
    if existing:
        db["account"].update_one({"_id": existing["_id"]}, {"$set": {
            "provider": "github",
            "github_username": gh.get("login"),
            "avatar_url": gh.get("avatar_url"),
            "updated_at": datetime.utcnow(),
        }})
        acc_id = existing["_id"]
    else:
        acc_id = db["account"].insert_one({
            "email": email,
            "hashed_password": "",
            "name": gh.get("name"),
            "plan": "individual",
            "provider": "github",
            "github_username": gh.get("login"),
            "avatar_url": gh.get("avatar_url"),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }).inserted_id

    jwt_token = create_access_token({"sub": str(acc_id), "email": email})
    # Redirect back to frontend with token in fragment
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    redirect_to = f"{frontend_url}/auth/callback#token={jwt_token}"
    return RedirectResponse(url=redirect_to)


@app.post("/api/repos/connect")
def connect_repo(body: RepoConnectBody, user=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    repo = body.repo_full_name.strip()
    if "/" not in repo:
        raise HTTPException(status_code=400, detail="Invalid repo format. Use owner/repo")
    doc = {
        "account_id": user["id"],
        "provider": "github",
        "repo_full_name": repo,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    db["repoconnection"].insert_one(doc)
    return {"status": "ok", "message": "Repository connected", "repo": repo}

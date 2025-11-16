import os
import json
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
WAITLIST_FILE = DATA_DIR / "waitlist.json"
SAMPLE_REPORT = STATIC_DIR / "sample_report.pdf"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="SentinelAI Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class WaitlistEntry(BaseModel):
    email: EmailStr


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


@app.get("/")
def read_root():
    return {"message": "SentinelAI Backend is running"}


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


@app.get("/test")
def test():
    return {
        "backend": "running",
        "waitlist_count": len(load_waitlist()),
        "has_report": SAMPLE_REPORT.exists(),
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

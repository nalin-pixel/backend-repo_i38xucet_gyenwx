# SentinelAI

Modern landing with news aggregator, waitlist, sample report, and authentication.

## Environment

Frontend:
- VITE_BACKEND_URL (e.g., https://your-backend.host)

Backend:
- PORT (default 8000)
- BACKEND_URL (public backend base, for GitHub OAuth callback)
- FRONTEND_URL (public frontend base, for redirect)
- JWT_SECRET (any random string)
- DATABASE_URL, DATABASE_NAME (MongoDB)
- GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET (for OAuth)

## Auth
- Email/password signup and login with JWT
- Toggle Individual vs Team during signup
- GitHub OAuth available; redirects to frontend with token

## News
- GET /api/news?page=1&page_size=12 with caching, dedupe, sorting

## Repo connect
- POST /api/repos/connect with Authorization: Bearer <token>, body { repo_full_name: "owner/repo" }


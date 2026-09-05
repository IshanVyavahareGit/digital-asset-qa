# Postman collection — Esports Visual QA backend

`Esports_Visual_QA.postman_collection.json` exercises every backend endpoint,
grouped by requirement tier, with a description on each request.

## 1. Run the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# optional: enable the two AI checks (typo/roster, design/theme)
cp .env.example .env                 # then paste your GEMINI_API_KEY into .env

# assets are already generated & committed; to regenerate:
# python ../assets/generate_assets.py

uvicorn app.main:app --reload --port 8000
```

On first boot the server creates `backend/data/app.db` and seeds two users:

| Role | Email | Password |
|------|-------|----------|
| Manager (upload, evaluate, override) | `manager@tec.dev` | `manager123` |
| Designer (read-only) | `designer@tec.dev` | `designer123` |

Sanity check: open http://localhost:8000/health → `{"status":"ok"}`.
Interactive docs (an alternative to Postman): http://localhost:8000/docs

> Without `GEMINI_API_KEY`, the typo/roster and design/theme checks honestly report
> `failed` and the sponsor-audit + safe-zone checks still run. Use graphic **g09**
> (missing sponsor) to see a real finding with no key required.

## 2. Import & run the collection

1. Postman → Import → select the `.json` file.
2. The collection ships its own variables (`baseUrl = http://localhost:8000`, plus
   `assetsDir` pointing at `assets/graphics`). No separate environment needed.
3. Run requests roughly in order:
   - **01 Auth → Login (manager)** first — saves `{{managerToken}}`.
   - **02 Tier 1 → Upload & evaluate (g09)** — saves `{{reviewId}}` and `{{findingId}}`.
   - Everything else chains off those saved variables.

You can also run the whole collection at once with the Postman **Collection Runner**
(top-to-bottom order works because IDs are captured as they go).

## 3. File uploads

The file requests reference `assets/graphics/*.png` via an absolute `src` path
(`{{assetsDir}}`). If Postman flags a file as missing (e.g. you moved the repo),
open that request's **Body** tab and re-select the file — the rest still works.
